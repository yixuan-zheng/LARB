"""S9: does one switch at the prefill/decode boundary capture the static prefill win?

Purpose in the extension
------------------------
The static profile's only appreciable width effect is prefill (S2: 1.14-1.21x; S5 eager
1.22x). A single switchable model can, in principle, take that win for free: run the
compute-bound prefill at the narrow width, then switch to the wide width for decode so the
tokens it generates are the quality ones. This scenario prices exactly that idea.

Conditions (all measured in the same interleaved rounds so the pairing is valid)
--------------------------------------------------------------------------------
* ``static_small``         -- the static baseline a fixed narrow model would give.
* ``dyn_large``            -- the wide reference; decode quality, no switch.
* ``dyn_small``            -- the narrow reference; both phases narrow.
* ``phase_small_to_large`` -- narrow prefill, one switch, wide decode.
* ``phase_large_to_small`` -- the mirror: wide prefill, narrow decode.

Metrics and the derived quantities
----------------------------------
Per condition: prefill (wall and device), TTFT, steady-state ITL p50/p90/p99 (the first
decode step is excluded because for the phase schedules it *is* the boundary), E2E and
decode tokens/second. Two derived numbers carry the claim:

* ``capture_fraction`` = (prefill_large - prefill_phase)/(prefill_large - prefill_small),
  i.e. what share of the full static prefill win the mixed schedule actually banks.
* ``boundary_switch_cost`` = first-decode-step median minus the steady-state ITL at the
  destination width, i.e. what the switch itself adds to the token right after it.

Generations are expensive, so ``reps`` counts whole generations and the per-step samples
within a generation are retained as the ITL distribution (as in S4).
"""
from __future__ import annotations

import argparse

import torch

import dynamic_lib as dyn
import latency_lib as lib
import latency_math as lm
import switch_schedules as sched

SCENARIO = "s9_switch_phase"


def summarize_runs(runs: list) -> dict:
    """Aggregate whole generations into the S9 metric set."""
    prefill_gpu = [r["prefill_gpu_ms"] for r in runs]
    prefill_wall = [r["prefill_wall_ms"] for r in runs]
    ttft = [r["ttft_ms"] for r in runs]
    e2e = [r["e2e_ms"] for r in runs]
    # Steady-state ITL drops the first decode step: for the phase schedules that step
    # is the boundary itself, and folding it in would hide the very cost being measured.
    steady = sorted(s["wall_ms"] for r in runs for s in r["steps"][1:])
    first = [r["steps"][0]["wall_ms"] for r in runs if r["steps"]]
    switches = [v for r in runs for v in r["switch_ms"]]
    return {"n_runs": len(runs),
            "prefill_gpu_ms": lm.summarize(prefill_gpu),
            "prefill_wall_ms": lm.summarize(prefill_wall),
            "ttft_ms": lm.summarize(ttft), "e2e_ms": lm.summarize(e2e),
            "itl_ms": (lm.summarize(steady) if steady else None),
            "first_step_ms": (lm.summarize(first) if first else None),
            "switch_apply_ms": (lm.summarize(switches) if switches else None)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=3, default_warmup=1)
    parser.add_argument("--prompt-lengths", default="512,2048")
    parser.add_argument("--batch-sizes", default="1,4")
    parser.add_argument("--new-tokens", type=int, default=32)
    parser.add_argument("--statics", default="small")
    parser.add_argument("--slice-mode", default="view", choices=list(dyn.SLICE_MODES))
    parser.add_argument("--prompt-offset", type=int, default=0)
    args = parser.parse_args()
    prompt_lengths = [int(x) for x in args.prompt_lengths.split(",") if x.strip()]
    batch_sizes = [int(x) for x in args.batch_sizes.split(",") if x.strip()]
    statics = [p.strip() for p in args.statics.split(",") if p.strip()]
    if statics != ["small"]:
        raise SystemExit("s9 currently pairs against a static 'small' baseline only")

    protocol = lib.prepare_runtime(args)
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks)
    record.set_protocol(warmup=args.warmup, reps=args.reps, new_tokens=args.new_tokens,
                        prompt_lengths=prompt_lengths, batch_sizes=batch_sizes,
                        statics=statics, slice_mode=args.slice_mode, interleaved=True,
                        shuffled=True, flush_l2=args.flush_l2, flush_mb=args.flush_mb,
                        greedy=True, eos_ignored=True, prompt_offset=args.prompt_offset)
    if args.estimate_only:
        grid = len(prompt_lengths) * len(batch_sizes) * 5
        print(lib.estimate_wall_time(grid, args.reps, args.warmup,
                                     60.0 + 60.0 * args.new_tokens))
        return

    print("[s9] clock ramp ...", flush=True)
    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")

    print(f"[s9] building switchable model (statics={statics})", flush=True)
    dynamic, controller, static_workers, tokenizer, infos = dyn.build_switchable(
        lib.dtype_of(args), statics=statics, slice_mode=args.slice_mode)
    lib.reset_peak_memory()
    record.set_extra("dynamic_describe", controller.describe())
    record.set_extra("workers", infos)
    spec = lib.arch_spec_from_config(dynamic.config, model=dynamic)
    dtype_bytes = lib.DTYPE_BYTES[args.dtype]
    widths_map = sched.load_preset_widths()
    plans = {p: sched.WidthPlan.from_preset(p, widths_map)
             for p in ("small", "medium", "large")}

    iterations = args.new_tokens + 1
    conditions = [
        {"key": "static_small", "model": "static", "schedule": None},
        {"key": "dyn_large", "model": "dynamic", "schedule": "const:large"},
        {"key": "dyn_small", "model": "dynamic", "schedule": "const:small"},
        {"key": "phase_small_to_large", "model": "dynamic", "schedule": "phase:small:large"},
        {"key": "phase_large_to_small", "model": "dynamic", "schedule": "phase:large:small"},
    ]
    for cond in conditions:
        cond["_plans"] = (None if cond["schedule"] is None
                          else sched.resolve_schedule(cond["schedule"], iterations,
                                                      args.seed, widths_map)[1])

    prompts, hashes = {}, {}
    for prompt_len in prompt_lengths:
        ids, digest = lib.build_prompt_ids(tokenizer, prompt_len, args.prompt_offset)
        prompts[prompt_len] = ids.to("cuda")
        hashes[str(prompt_len)] = digest
    record.set_extra("prompt_sha256", hashes)

    harness = lib.Harness(args)
    record.set_extra("flusher", harness.flusher.describe())

    switching = {"grids": {}}
    with torch.inference_mode():
        for prompt_len in prompt_lengths:
            for batch in batch_sizes:
                grid_key = f"L{prompt_len}_B{batch}"
                budgets = {
                    "dynamic_large": lib.vram_budget_check(spec, plans["large"].widths,
                                                           batch, prompt_len, dtype_bytes),
                    "static_small": lib.vram_budget_check(spec, plans["small"].widths,
                                                          batch, prompt_len, dtype_bytes),
                }
                record.set_extra(f"vram_check_{grid_key}", budgets)
                if not budgets["dynamic_large"]["ok"]:
                    print(f"[s9] {grid_key}: SKIPPED (VRAM budget)", flush=True)
                    switching["grids"][grid_key] = {
                        "skipped_reason": budgets["dynamic_large"].get("skipped_reason")}
                    continue
                prompt = prompts[prompt_len].repeat(batch, 1).contiguous()
                runs = {c["key"]: [] for c in conditions}
                print(f"[s9] {grid_key}: {args.warmup}w+{args.reps}r x {len(conditions)} conds "
                      f"x {args.new_tokens} tokens", flush=True)
                for rep in range(args.warmup + args.reps):
                    order = list(conditions)
                    harness.rng.shuffle(order)
                    for cond in order:
                        model = dynamic if cond["model"] == "dynamic" else static_workers["small"]
                        ctrl = controller if cond["model"] == "dynamic" else None
                        plan_list = cond["_plans"] if cond["model"] == "dynamic" else None
                        result = dyn.run_generation(harness.timer, harness.flusher, model, ctrl,
                                                    prompt, plan_list, args.new_tokens)
                        if rep >= args.warmup:
                            runs[cond["key"]].append(result)

                summary = {c["key"]: summarize_runs(runs[c["key"]]) for c in conditions}
                for value in summary.values():
                    value["decode_tok_s"] = (batch / (value["itl_ms"]["median"] / 1000.0)
                                             if value["itl_ms"] else None)
                    value["batch"], value["prompt_len"] = batch, prompt_len
                wide, narrow = summary["dyn_large"], summary["dyn_small"]
                s2l, l3s = summary["phase_small_to_large"], summary["phase_large_to_small"]
                wide_pf = [r["prefill_gpu_ms"] for r in runs["dyn_large"]]
                narrow_pf = [r["prefill_gpu_ms"] for r in runs["dyn_small"]]
                delta = wide["prefill_gpu_ms"]["median"] - narrow["prefill_gpu_ms"]["median"]
                # The capture fraction divides by the static large-minus-small *prefill*
                # difference. At low arithmetic intensity (short prompt, batch 1) S2/S5
                # showed that difference is ~0, so the ratio amplifies noise and can exceed
                # 1. Gate it on the paired large-vs-small prefill being a pre-registered
                # "appreciable" effect; otherwise keep the raw value but mark it unresolved.
                resolution = (lm.paired_stats(wide_pf, narrow_pf, seed=args.seed)
                              if len(wide_pf) >= 2 and len(wide_pf) == len(narrow_pf) else None)
                resolvable = bool(resolution and resolution["appreciable"])
                capture_raw = ((wide["prefill_gpu_ms"]["median"] - s2l["prefill_gpu_ms"]["median"])
                               / delta) if delta else None
                entry = {
                    "conditions": summary,
                    "prefill_delta_ms": delta,
                    "prefill_delta_pct": (100.0 * delta / narrow["prefill_gpu_ms"]["median"]
                                          if narrow["prefill_gpu_ms"]["median"] else None),
                    "prefill_delta_resolution": resolution,
                    "capture_resolvable": resolvable,
                    "prefill_capture_fraction_raw": capture_raw,
                    "prefill_capture_fraction": capture_raw if resolvable else None,
                    "boundary_switch_cost_ms": {
                        "small_to_large": s2l["first_step_ms"]["median"] - wide["itl_ms"]["median"],
                        "large_to_small": l3s["first_step_ms"]["median"] - narrow["itl_ms"]["median"]},
                    "comparisons": {},
                }
                for a, b, label in (("phase_small_to_large", "dyn_large", "phase_s2l_vs_dyn_large"),
                                    ("phase_small_to_large", "static_small", "phase_s2l_vs_static_small"),
                                    ("phase_large_to_small", "dyn_small", "phase_l3s_vs_dyn_small")):
                    left = [r["e2e_ms"] for r in runs[a]]
                    right = [r["e2e_ms"] for r in runs[b]]
                    n = min(len(left), len(right))
                    if n >= 2:
                        entry["comparisons"][label] = lm.paired_stats(left[:n], right[:n],
                                                                      seed=args.seed)
                switching["grids"][grid_key] = entry
                record.set_extra("switching", switching)
                if resolvable:
                    cap_str = f"{capture_raw:.3f}"
                elif capture_raw is not None:
                    cap_str = f"n/a (raw {capture_raw:.2f})"
                else:
                    cap_str = "n/a"
                print(f"[s9]   {grid_key:<12} capture={cap_str} prefill_delta={delta:.2f}ms "
                      f"boundary_s2l={entry['boundary_switch_cost_ms']['small_to_large']:.2f}ms "
                      f"boundary_l3s={entry['boundary_switch_cost_ms']['large_to_small']:.2f}ms",
                      flush=True)

    record.set_extra("switching", switching)
    record.set_extra("peak_memory", lib.peak_memory_snapshot())
    record.set_extra("clocks_at_end", lib.clocks_snapshot())
    record.complete()
    print("PASS s9_switch_phase", flush=True)


if __name__ == "__main__":
    main()

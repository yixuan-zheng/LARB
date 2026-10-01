"""S10: iteration-level switching inside decode -- where an overhead is most plausible.

Purpose in the extension
------------------------
S1 and S3 established that a *static* width change does nothing to decode: the step is
~54 ms of launch-bound small kernels, not a weight stream. So the interesting question is
not whether a narrow decode is faster; it is whether **alternating shapes every token is
slower than the average of the two shapes**, which is what a naive dynamic policy would
do. Each switch touches all 35 layers, changes the GEMM shape on the next forward, and
defeats whatever per-shape kernel caching a static run enjoys.

Schedules (each is a per-forward plan list; index 0 is the prefill width)
------------------------------------------------------------------------
* ``const:large`` / ``const:small`` -- the two static references.
* ``alternate:large:small``          -- a switch every single token (worst case).
* ``block:large:small:k`` for k=1,4,16 -- switch frequency sweep.
* ``random:large:small``             -- a seeded, unpatterned worst case.

A quality-aware adaptive/early-exit policy is deliberately out of scope: any schedule here
changes the model's outputs by construction, so it is reported as a latency mechanism only,
never as a quality claim.

Derived quantities
------------------
* ``alternation_overhead_pct`` = (measured mean step - width-weighted static prediction)
  / prediction, where the prediction is the mean of the per-width const medians over the
  schedule's own plans. This isolates the cost of *switching itself* from the cost of the
  widths being switched between.
* per-switch host cost (``switch_apply_ms``) and the p99 step, which is where a cold-shape
  penalty would show up as a tail rather than a mean shift.
"""
from __future__ import annotations

import argparse

import torch

import dynamic_lib as dyn
import latency_lib as lib
import latency_math as lm
import switch_schedules as sched

SCENARIO = "s10_switch_iteration"
SCHEDULES = ("const:large", "const:small", "alternate:large:small",
             "block:large:small:1", "block:large:small:4", "block:large:small:16",
             "random:large:small")


def summarize_steps(runs: list) -> dict:
    """Per-step distribution for one schedule across whole generations."""
    steps = [s for r in runs for s in r["steps"]]
    wall = sorted(s["wall_ms"] for s in steps)
    switches = [v for r in runs for v in r["switch_ms"]]
    return {"n_runs": len(runs), "n_steps": len(steps),
            "step_wall_ms": lm.summarize(wall) if wall else None,
            "switch_apply_ms": lm.summarize(switches) if switches else None,
            "n_switches": len(switches)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=3, default_warmup=1)
    parser.add_argument("--context-lengths", default="512,2048")
    parser.add_argument("--batch-sizes", default="1,8")
    parser.add_argument("--new-tokens", type=int, default=48)
    parser.add_argument("--statics", default="small")
    parser.add_argument("--slice-mode", default="view", choices=list(dyn.SLICE_MODES))
    parser.add_argument("--schedules", default=",".join(SCHEDULES))
    parser.add_argument("--prompt-offset", type=int, default=0)
    args = parser.parse_args()
    context_lengths = [int(x) for x in args.context_lengths.split(",") if x.strip()]
    batch_sizes = [int(x) for x in args.batch_sizes.split(",") if x.strip()]
    statics = [p.strip() for p in args.statics.split(",") if p.strip()]
    if statics != ["small"]:
        raise SystemExit("s10 pairs against a static 'small' baseline only")
    schedule_specs = [s.strip() for s in args.schedules.split(",") if s.strip()]

    protocol = lib.prepare_runtime(args)
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks)
    record.set_protocol(warmup=args.warmup, reps=args.reps, new_tokens=args.new_tokens,
                        context_lengths=context_lengths, batch_sizes=batch_sizes,
                        statics=statics, slice_mode=args.slice_mode, schedules=schedule_specs,
                        interleaved=True, shuffled=True, flush_l2=args.flush_l2,
                        flush_mb=args.flush_mb, greedy=True, eos_ignored=True,
                        prompt_offset=args.prompt_offset)
    if args.estimate_only:
        grid = len(context_lengths) * len(batch_sizes) * len(schedule_specs)
        print(lib.estimate_wall_time(grid, args.reps, args.warmup, 60.0 + 55.0 * args.new_tokens))
        return

    print("[s10] clock ramp ...", flush=True)
    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")

    print(f"[s10] building switchable model (statics={statics})", flush=True)
    dynamic, controller, static_workers, tokenizer, infos = dyn.build_switchable(
        lib.dtype_of(args), statics=statics, slice_mode=args.slice_mode)
    lib.reset_peak_memory()
    record.set_extra("dynamic_describe", controller.describe())
    record.set_extra("workers", infos)
    spec = lib.arch_spec_from_config(dynamic.config, model=dynamic)
    dtype_bytes = lib.DTYPE_BYTES[args.dtype]
    widths_map = sched.load_preset_widths()
    plan_large = sched.WidthPlan.from_preset("large", widths_map)
    iterations = args.new_tokens + 1

    conditions = []
    for spec_str in schedule_specs:
        name, plans = sched.resolve_schedule(spec_str, iterations, args.seed, widths_map)
        conditions.append({"key": name, "spec": spec_str, "plans": plans, "model": "dynamic"})
    existing = {c["spec"] for c in conditions}
    for ref in ("const:large", "const:small"):
        if ref not in existing:
            name, plans = sched.resolve_schedule(ref, iterations, args.seed, widths_map)
            conditions.append({"key": name, "spec": ref, "plans": plans, "model": "dynamic"})
    conditions.append({"key": "static_small", "spec": "static", "plans": None, "model": "static"})

    prompts, hashes = {}, {}
    for ctx_len in context_lengths:
        ids, digest = lib.build_prompt_ids(tokenizer, ctx_len, args.prompt_offset)
        prompts[ctx_len] = ids.to("cuda")
        hashes[str(ctx_len)] = digest
    record.set_extra("prompt_sha256", hashes)

    harness = lib.Harness(args)
    record.set_extra("flusher", harness.flusher.describe())

    switching = {"grids": {}}
    with torch.inference_mode():
        for ctx_len in context_lengths:
            for batch in batch_sizes:
                grid_key = f"L{ctx_len}_B{batch}"
                budget = lib.vram_budget_check(spec, plan_large.widths, batch,
                                               max(ctx_len, 1), dtype_bytes)
                record.set_extra(f"vram_check_{grid_key}", budget)
                if not budget["ok"]:
                    print(f"[s10] {grid_key}: SKIPPED (VRAM budget)", flush=True)
                    switching["grids"][grid_key] = {"skipped_reason": budget.get("skipped_reason")}
                    continue
                prompt = prompts[ctx_len].repeat(batch, 1).contiguous()
                runs = {c["key"]: [] for c in conditions}
                print(f"[s10] {grid_key}: {args.warmup}w+{args.reps}r x {len(conditions)} schedules "
                      f"x {args.new_tokens} tokens", flush=True)
                for rep in range(args.warmup + args.reps):
                    order = list(conditions)
                    harness.rng.shuffle(order)
                    for cond in order:
                        if cond["model"] == "static":
                            model, ctrl, plan_list = static_workers["small"], None, None
                        else:
                            model, ctrl, plan_list = dynamic, controller, cond["plans"]
                        result = dyn.run_generation(harness.timer, harness.flusher, model, ctrl,
                                                    prompt, plan_list, args.new_tokens)
                        if rep >= args.warmup:
                            runs[cond["key"]].append(result)

                summary = {c["key"]: summarize_steps(runs[c["key"]]) for c in conditions}
                per_width = {w: summary[f"const_{w}"]["step_wall_ms"]["median"]
                             for w in ("large", "small")
                             if summary.get(f"const_{w}") and summary[f"const_{w}"]["step_wall_ms"]}
                entry = {"per_width_step_ms": per_width, "conditions": {}, "comparisons": {},
                         "batch": batch, "ctx_len": ctx_len}
                for cond in conditions:
                    s = summary[cond["key"]]
                    record_cond = {"spec": cond["spec"], **s}
                    if cond["model"] == "dynamic" and cond["plans"] and len(per_width) == 2:
                        decode_plans = cond["plans"][1:]
                        try:
                            predicted = sched.width_weighted_ms(per_width, decode_plans)
                        except KeyError:
                            predicted = None
                        record_cond["predicted_step_ms"] = predicted
                        if predicted and s["step_wall_ms"]:
                            record_cond["alternation_overhead_pct"] = (
                                100.0 * (s["step_wall_ms"]["mean"] - predicted) / predicted)
                    entry["conditions"][cond["key"]] = record_cond
                # How big is the width effect this grid is trying to switch between? If the
                # static large and small steps are indistinguishable here (S1/S3 say they are
                # at every batch/context this suite measured), then the alternation overhead
                # is within noise by construction and must not be read as "switching is free".
                entry["const_width_delta_ms"] = (per_width.get("large", 0.0)
                                                 - per_width.get("small", 0.0))
                step_large = [s["wall_ms"] for r in runs["const_large"] for s in r["steps"]]
                step_small = [s["wall_ms"] for r in runs["const_small"] for s in r["steps"]]
                if len(step_large) == len(step_small) and len(step_large) >= 2:
                    width_res = lm.paired_stats(step_large, step_small, seed=args.seed)
                    entry["width_effect_resolution"] = width_res
                    entry["width_effect_resolvable"] = bool(width_res["appreciable"])
                else:
                    entry["width_effect_resolvable"] = None
                base = [r["e2e_ms"] for r in runs["const_large"]]
                for cond in conditions:
                    if cond["key"] == "const_large":
                        continue
                    other = [r["e2e_ms"] for r in runs[cond["key"]]]
                    n = min(len(base), len(other))
                    if n >= 2:
                        entry["comparisons"][f"{cond['key']}_vs_const_large"] = lm.paired_stats(
                            base[:n], other[:n], seed=args.seed)
                switching["grids"][grid_key] = entry
                record.set_extra("switching", switching)
                alt = entry["conditions"].get("alt_large_small", {})
                alt_over = alt.get("alternation_overhead_pct")
                print(f"[s10]   {grid_key:<12} alt_overhead="
                      f"{'n/a' if alt_over is None else f'{alt_over:+.2f}%'} "
                      f"n_switches={alt.get('n_switches')}", flush=True)

    record.set_extra("switching", switching)
    record.set_extra("peak_memory", lib.peak_memory_snapshot())
    record.set_extra("clocks_at_end", lib.clocks_snapshot())
    record.complete()
    print("PASS s10_switch_iteration", flush=True)


if __name__ == "__main__":
    main()

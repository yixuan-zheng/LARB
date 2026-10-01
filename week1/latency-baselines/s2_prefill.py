"""S2: prefill (prompt processing) latency vs prompt length and batch size.

Purpose in the ladder
---------------------
S1 predicts a flat Large/Small ratio because a batch-1, one-token step is dominated by
per-call dispatch overhead (S0 measured ~87 us per invocation across ~455 invocations
per forward). Prefill is the natural place for the width effect to appear: it is one
large GEMM per projection instead of one skinny GEMV, so

  * arithmetic intensity rises, so the GPU can actually use the FFN width, and
  * the fixed overhead is amortized over ``batch * prompt_len`` tokens instead of one.

If narrowing 20 of 35 FFNs from 16384 to 8192 never pays off here, it does not pay off
for prefill, which is the strongest single claim this suite can make.

Workload definition and why it was chosen
-----------------------------------------
* Prompt lengths 128 / 512 / 2048 / 4096 tokens, built by tiling real text to an exact
  length and hashing the token ids into the record.
  - 128 = chat-style short prompt; FFN-dominated per token.
  - 512 = the sliding-window scale.
  - 2048 / 4096 = long-document prefill, where attention begins to matter.
* Batch sizes 1 / 4 / 16. The batch is the *same* prompt repeated, which is deliberate:
  identical rows make the batch a pure width of the GEMM, without the confounding effect
  of ragged lengths or padding masks. For latency this is equivalent to distinct prompts;
  it is not a claim about batching diverse traffic.
* One measured forward per iteration, ``use_cache=True`` so a KV cache is materialised
  exactly as a real server would, ``logits_to_keep=1`` so the LM head is not the story.
  There is no per-iteration preparation to exclude: the whole forward is the metric.

Metrics
-------
``prefill_wall_ms``, ``prefill_gpu_ms`` (device only), the derived ``alpha_ms``,
``prefill_tok_s`` = ``batch * prompt_len / gpu_seconds``, plus achieved bandwidth and MFU
from the analytic model. ``ffn_flop_share`` is recorded so the reader can see how much of
this workload is even in scope for a width change.

Safety
------
Large ``batch * prompt_len`` configurations can exhaust a 45 GiB device when three workers
are resident, so every grid point is budget-checked against live free VRAM and recorded as
``skipped_reason`` rather than allowed to crash the sweep.
"""
from __future__ import annotations

import argparse

import torch

import build_worker
import latency_lib as lib

SCENARIO = "s2_prefill"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=30, default_warmup=8)
    parser.add_argument("--prompt-lengths", default="128,512,2048")
    parser.add_argument("--batch-sizes", default="1,4")
    parser.add_argument("--prompt-offset", type=int, default=0)
    args = parser.parse_args()
    prompt_lengths = [int(x) for x in args.prompt_lengths.split(",") if x.strip()]
    batch_sizes = [int(x) for x in args.batch_sizes.split(",") if x.strip()]
    presets = lib.selected_presets(args)

    protocol = lib.prepare_runtime(args)
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks, presets=presets)
    record.set_protocol(warmup=args.warmup, reps=args.reps, interleaved=True, shuffled=True,
                        cache="materialised_per_iteration", logits_to_keep=1,
                        flush_l2=args.flush_l2, flush_mb=args.flush_mb,
                        prompt_lengths=prompt_lengths, batch_sizes=batch_sizes,
                        batch_construction="same prompt repeated",
                        prompt_offset=args.prompt_offset)
    if args.estimate_only:
        print(lib.estimate_wall_time(len(prompt_lengths) * len(batch_sizes) * len(presets),
                                     args.reps, args.warmup, 250.0))
        return

    print("[s2] clock ramp ...", flush=True)
    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")

    print(f"[s2] building workers: {presets}", flush=True)
    workers, tokenizer, infos = build_worker.build_workers(presets, lib.dtype_of(args))
    lib.reset_peak_memory()

    specs, widths, total_bytes = {}, {}, {}
    for preset in presets:
        spec = lib.arch_spec_from_config(workers[preset].config, model=workers[preset])
        specs[preset], widths[preset] = spec, list(spec.widths)
        total_bytes[preset] = infos[preset]["param_bytes"]["total"]
        with torch.inference_mode():
            infos[preset]["smoke"] = build_worker.smoke_test(workers[preset], tokenizer)
    record.set_extra("workers", infos)

    prompts, hashes = {}, {}
    for prompt_len in prompt_lengths:
        ids, digest = lib.build_prompt_ids(tokenizer, prompt_len, args.prompt_offset)
        prompts[prompt_len] = ids.to("cuda")
        hashes[str(prompt_len)] = digest
    record.set_extra("prompt_sha256", hashes)

    harness = lib.Harness(args)
    record.set_extra("flusher", harness.flusher.describe())
    dtype_bytes = lib.DTYPE_BYTES[args.dtype]
    derived_all, skipped = {}, []

    with torch.inference_mode():
        for prompt_len in prompt_lengths:
            for batch in batch_sizes:
                grid_key = f"L{prompt_len}_B{batch}"
                budgets = {p: lib.vram_budget_check(specs[p], widths[p], batch, prompt_len, dtype_bytes)
                           for p in presets}
                runnable = [p for p in presets if budgets[p]["ok"]]
                record.set_extra(f"vram_check_{grid_key}", budgets)
                if len(runnable) < len(presets):
                    skipped.append({"grid": grid_key, "skippable": [p for p in presets
                                                                     if not budgets[p]["ok"]],
                                    "reason": "activation estimate exceeds VRAM budget"})
                    record.set_extra("skipped_configs", skipped)
                if not runnable:
                    print(f"[s2] {grid_key}: SKIPPED (VRAM budget)", flush=True)
                    continue

                # The batch is the configured batch size. An earlier version used
                # ``len(runnable)`` here, which silently coupled the measured batch to
                # the number of presets and made every derived per-token metric wrong.
                ids = prompts[prompt_len].repeat(batch, 1).contiguous()
                configs = [{"key": f"{p}_{grid_key}", "preset": p, "prompt_len": prompt_len,
                            "batch": batch, "tokens": batch * prompt_len} for p in runnable]

                def step(cfg, state):
                    return workers[cfg["preset"]](input_ids=ids, use_cache=True, logits_to_keep=1)

                print(f"[s2] {grid_key}: {args.warmup} warmup + {args.reps} reps x "
                      f"{len(configs)} presets ({[c['preset'] for c in configs]})", flush=True)
                samples = harness.sweep(configs, lambda cfg: None, step, args.warmup,
                                        args.reps, record=record)
                summary = lib.summarize_samples(samples)
                record.set_summary(grid_key, summary)

                for cfg in configs:
                    preset = cfg["preset"]
                    gpu = summary[cfg["key"]]["gpu_ms"]["median"]
                    d = lib.derived_metrics(specs[preset], widths[preset], total_bytes[preset],
                                            peaks, gpu, batch, prompt_len, prompt_len)
                    d["prefill_tok_s"] = (batch * prompt_len) / (gpu / 1000.0) if gpu else None
                    d["alpha_ms"] = summary[cfg["key"]]["alpha_ms"]["median"]
                    d["tokens_per_step"] = batch * prompt_len
                    derived_all[cfg["key"]] = d
                record.set_extra("derived", derived_all)

                baseline = "large" if "large" in runnable else runnable[-1]
                for metric in ("wall_ms", "gpu_ms"):
                    for preset in runnable:
                        if preset == baseline:
                            continue
                        record.set_comparison(f"{grid_key}/{preset}_vs_{baseline}/{metric}",
                                              lib.compare_pairs(samples, f"{baseline}_{grid_key}",
                                                                f"{preset}_{grid_key}", metric=metric,
                                                                seed=args.seed))
                for preset in runnable:
                    if preset == baseline:
                        continue
                    v = record.data["comparisons"][f"{grid_key}/{preset}_vs_{baseline}/gpu_ms"]
                    print(f"[s2]   {grid_key:<14} {preset+'/gpu':<10} speedup={v['speedup']:.4f} "
                          f"ci=[{v['ratio_lo']:.3f},{v['ratio_hi']:.3f}] "
                          f"mdd={v['mdd_pct']:.1f}% -> {v['verdict']}", flush=True)

        record.set_extra("clocks_at_end", lib.clocks_snapshot())
        record.set_extra("peak_memory", lib.peak_memory_snapshot())

    record.complete()
    print("PASS s2_prefill", flush=True)


if __name__ == "__main__":
    main()

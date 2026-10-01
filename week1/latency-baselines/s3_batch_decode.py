"""S3: batched decode-step latency, the throughput-relevant regime.

Purpose in the ladder
---------------------
A decode step must read every parameter once regardless of batch size, so batching makes
that fixed byte cost buy more tokens. S3 sweeps the batch to answer two questions:

1. Does the Large/Small *time* ratio move at all with batch? Theory says it should barely
   move for absolute step latency (weights are read once either way) but that the
   *tokens/second* ratio tracks the time ratio, so batching is where a width reduction
   converts into served throughput rather than into latency.
2. At what batch does the per-step time stop being dominated by ``alpha`` (S0: ~87 us per
   invocation x ~455 invocations per forward)?

Workload definition and why it was chosen
-----------------------------------------
* Batch sizes 1 / 2 / 4 / 8 / 16 / 32, context lengths 1 / 128 / 2048 tokens.
  - batch 1 anchors against S1; 32 is where a 45 GiB device with one worker still has
    headroom, and it is a realistic single-stream server batch.
  - context 1 isolates pure weight streaming with almost no KV traffic; 128 and 2048 add
    the width-independent KV/attention term that must dilute the benefit.
* The batch is the same real prompt repeated (see S2 for the rationale).
* One measured decode step per iteration, at exactly ``ctx_len`` cached tokens: the
  prefill lives in ``prepare`` and is excluded from the timed region, so the cache length
  is constant across presets, batches and reps.

Metrics
-------
``itl_wall_ms`` / ``itl_gpu_ms`` (inter-token latency per step, not per token),
``alpha_ms``, and ``decode_tok_s`` = ``batch / gpu_seconds``. Achieved bandwidth uses
parameters plus the analytic resident KV for that batch and context, and is a lower bound.
"""
from __future__ import annotations

import argparse

import torch

import build_worker
import latency_lib as lib
import latency_math as lm

SCENARIO = "s3_batch_decode"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=30, default_warmup=8)
    parser.add_argument("--context-lengths", default="1,128,2048")
    parser.add_argument("--batch-sizes", default="1,4,16,32")
    parser.add_argument("--prompt-offset", type=int, default=0)
    args = parser.parse_args()
    context_lengths = [int(x) for x in args.context_lengths.split(",") if x.strip()]
    batch_sizes = [int(x) for x in args.batch_sizes.split(",") if x.strip()]
    presets = lib.selected_presets(args)

    protocol = lib.prepare_runtime(args)
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks, presets=presets)
    record.set_protocol(warmup=args.warmup, reps=args.reps, interleaved=True, shuffled=True,
                        q_len=1, cache_mode="fresh_prefill_per_iteration",
                        prefill_outside_timed_region=True, batch_construction="same prompt repeated",
                        context_lengths=context_lengths, batch_sizes=batch_sizes,
                        flush_l2=args.flush_l2, flush_mb=args.flush_mb,
                        prompt_offset=args.prompt_offset)
    if args.estimate_only:
        print(lib.estimate_wall_time(len(context_lengths) * len(batch_sizes) * len(presets),
                                     args.reps, args.warmup, 300.0))
        return

    print("[s3] clock ramp ...", flush=True)
    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")

    print(f"[s3] building workers: {presets}", flush=True)
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

    one_id = lib.next_token_id(tokenizer, args.prompt_offset).to("cuda")
    prompts, hashes = {}, {}
    for ctx_len in context_lengths:
        ids, digest = lib.build_prompt_ids(tokenizer, ctx_len, args.prompt_offset)
        prompts[ctx_len] = ids.to("cuda")
        hashes[str(ctx_len)] = digest
    record.set_extra("prompt_sha256", hashes)
    record.set_extra("continuation_token_id", int(one_id.item()))

    harness = lib.Harness(args)
    record.set_extra("flusher", harness.flusher.describe())
    dtype_bytes = lib.DTYPE_BYTES[args.dtype]
    derived_all, skipped = {}, []

    with torch.inference_mode():
        for ctx_len in context_lengths:
            for batch in batch_sizes:
                grid_key = f"L{ctx_len}_B{batch}"
                budgets = {p: lib.vram_budget_check(specs[p], widths[p], batch, max(ctx_len, 1),
                                                    dtype_bytes) for p in presets}
                runnable = [p for p in presets if budgets[p]["ok"]]
                record.set_extra(f"vram_check_{grid_key}", budgets)
                if len(runnable) < len(presets):
                    skipped.append({"grid": grid_key,
                                    "skipped": [p for p in presets if not budgets[p]["ok"]],
                                    "reason": "activation estimate exceeds VRAM budget"})
                    record.set_extra("skipped_configs", skipped)
                if not runnable:
                    print(f"[s3] {grid_key}: SKIPPED (VRAM budget)", flush=True)
                    continue

                # Configured batch, not the number of presets (see the same fix in S2).
                prompt = prompts[ctx_len].repeat(batch, 1).contiguous()
                batch_ids = one_id.repeat(batch, 1)
                configs = [{"key": f"{p}_{grid_key}", "preset": p, "ctx_len": ctx_len,
                            "batch": batch} for p in runnable]

                def prepare(cfg):
                    out = workers[cfg["preset"]](input_ids=prompt, use_cache=True, logits_to_keep=1)
                    return out.past_key_values

                def step(cfg, cache):
                    return workers[cfg["preset"]](input_ids=batch_ids, past_key_values=cache,
                                                  use_cache=True, logits_to_keep=1)

                print(f"[s3] {grid_key}: {args.warmup} warmup + {args.reps} reps x "
                      f"{len(configs)} presets", flush=True)
                samples = harness.sweep(configs, prepare, step, args.warmup, args.reps, record=record)
                summary = lib.summarize_samples(samples)
                record.set_summary(grid_key, summary)

                for cfg in configs:
                    preset = cfg["preset"]
                    gpu = summary[cfg["key"]]["gpu_ms"]["median"]
                    kv = lm.kv_resident_bytes(specs[preset], ctx_len, batch, dtype_bytes)
                    d = lib.derived_metrics(specs[preset], widths[preset], total_bytes[preset],
                                            peaks, gpu, batch, 1, ctx_len, kv_bytes=kv)
                    d["kv_resident_bytes"] = kv
                    d["decode_tok_s"] = batch / (gpu / 1000.0) if gpu else None
                    d["alpha_ms"] = summary[cfg["key"]]["alpha_ms"]["median"]
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
                    ts = derived_all[f"{preset}_{grid_key}"]["decode_tok_s"]
                    tbl = derived_all[f"{baseline}_{grid_key}"]["decode_tok_s"]
                    print(f"[s3]   {grid_key:<13} {preset:<7} speedup={v['speedup']:.4f} "
                          f"ci=[{v['ratio_lo']:.3f},{v['ratio_hi']:.3f}] "
                          f"tok_s={ts:.1f} vs {tbl:.1f} -> {v['verdict']}", flush=True)

        record.set_extra("clocks_at_end", lib.clocks_snapshot())
        record.set_extra("peak_memory", lib.peak_memory_snapshot())

    record.complete()
    print("PASS s3_batch_decode", flush=True)


if __name__ == "__main__":
    main()

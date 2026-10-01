"""S1: single-request decode-step latency as a function of context length, batch 1.

Purpose in the ladder
---------------------
This is the *negative control* of the profile. The preflight pilot measured ~55 ms per
decode step at a 6-10 token context and saw a 0.98x Large/Small ratio. S1 reproduces
that regime deliberately and, crucially, measures the fixed per-call overhead ``alpha``
alongside it, so the reason for the flat ratio is quantified rather than assumed.

Workload definition and why it was chosen
-----------------------------------------
* One request, batch 1, greedy, one decode step measured per iteration.
* Context lengths 128 / 512 / 2048 / 8192 tokens, built by tiling real text to an exact
  length (``latency_lib.build_prompt_ids``) and hashed into the record.
  - 128 = steady-state short chat; the regime where FFN weight traffic is the largest
    share of the step, so it is the best case for a width win.
  - 512 = Gemma 3n's sliding-window scale, where most layers stop growing their KV.
  - 2048 = long-form prompt; the KV/attention term starts to compete with the FFN.
  - 8192 = deliberately KV-dominated, to test the prediction that the *relative*
    benefit of a narrower FFN must shrink as width-independent work grows.
* One continuation token, chosen from the real tokenizer vocabulary rather than a magic
  constant (the pilot used id 17; a real token keeps the workload honest).

Cache handling (the isolation requirement)
------------------------------------------
The prefill runs inside ``prepare``, which the harness executes *outside* the timed
region, and a fresh cache is built for every measured iteration. The measured decode
step therefore always sees exactly ``ctx_len`` cached tokens: constant across presets
and across reps, with no growth over the run and no dependence on a previous iteration's
state. This is a stronger guarantee than flushing, and it makes the L sweep a genuine
inter-token-latency-vs-position curve rather than a self-correlation of one cache.

Metrics
-------
``itl_wall_ms`` (what a caller feels, including host dispatch), ``itl_gpu_ms`` (device
time only) and the derived ``alpha_ms``. Derived utilization is computed from the
median of each, and reported as achieved bandwidth (lower bound: every parameter must be
read at least once) and MFU.
"""
from __future__ import annotations

import argparse
import json

import torch

import build_worker
import latency_lib as lib

SCENARIO = "s1_decode_step"


def cache_length(cache):
    """Best-effort cache length probe so the workload invariant is verified, not assumed."""
    for attr in ("get_seq_length", "get_max_cache_shape"):
        fn = getattr(cache, attr, None)
        if callable(fn) and attr == "get_seq_length":
            try:
                return int(fn())
            except Exception:
                pass
    layers = getattr(cache, "layers", None)
    if layers:
        try:
            return int(layers[0].keys.shape[-2])
        except Exception:
            pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=40, default_warmup=10)
    parser.add_argument("--context-lengths", default="128,512,2048",
                        help="comma-separated cached-token counts to measure")
    parser.add_argument("--prompt-offset", type=int, default=0)
    args = parser.parse_args()
    context_lengths = [int(x) for x in args.context_lengths.split(",") if x.strip()]
    presets = lib.selected_presets(args)

    protocol = lib.prepare_runtime(args)
    device_name = lib.device_info()["name"]
    peaks = lib.resolve_peaks(args, device_name)
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks, presets=presets)
    record.set_protocol(warmup=args.warmup, reps=args.reps, batch=1, q_len=1, greedy=True,
                        interleaved=True, shuffled=True, cache_mode="fresh_prefill_per_iteration",
                        prefill_outside_timed_region=True, flush_l2=args.flush_l2,
                        flush_mb=args.flush_mb, context_lengths=context_lengths,
                        prompt_offset=args.prompt_offset)
    if args.estimate_only:
        print(lib.estimate_wall_time(len(context_lengths) * len(presets), args.reps,
                                     args.warmup, 120.0))
        return

    print("[s1] clock ramp ...", flush=True)
    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")

    print(f"[s1] building workers: {presets}", flush=True)
    workers, tokenizer, infos = build_worker.build_workers(presets, lib.dtype_of(args))
    lib.reset_peak_memory()
    record.set_extra("workers", infos)

    specs, widths = {}, {}
    for preset in presets:
        spec = lib.arch_spec_from_config(workers[preset].config, model=workers[preset])
        specs[preset], widths[preset] = spec, list(spec.widths)
        with torch.inference_mode():
            infos[preset]["smoke"] = build_worker.smoke_test(workers[preset], tokenizer)
    record.set_extra("workers", infos)

    one_id = lib.next_token_id(tokenizer, args.prompt_offset).to("cuda")
    record.set_extra("continuation_token_id", int(one_id.item()))
    prompts = {}
    for ctx_len in context_lengths:
        ids, digest = lib.build_prompt_ids(tokenizer, ctx_len, args.prompt_offset)
        prompts[ctx_len] = (ids.to("cuda"), digest)
    record.set_extra("prompt_sha256", {str(k): v[1] for k, v in prompts.items()})

    harness = lib.Harness(args)
    record.set_extra("flusher", harness.flusher.describe())
    derived_all = {}
    with torch.inference_mode():
        for ctx_len in context_lengths:
            configs = [{"key": f"{p}_L{ctx_len}", "preset": p, "ctx_len": ctx_len}
                       for p in presets]

            def prepare(cfg):
                out = workers[cfg["preset"]](input_ids=prompts[ctx_len][0], use_cache=True,
                                             logits_to_keep=1)
                return out.past_key_values

            def step(cfg, cache):
                return workers[cfg["preset"]](input_ids=one_id, past_key_values=cache,
                                              use_cache=True, logits_to_keep=1)

            probe = prepare(configs[0])
            observed = cache_length(probe)
            record.set_extra(f"cache_len_probe_L{ctx_len}", observed)
            if observed is not None and observed != ctx_len:
                raise AssertionError(f"cache holds {observed} tokens, expected {ctx_len}")
            del probe

            print(f"[s1] L={ctx_len}: {args.warmup} warmup + {args.reps} reps x {len(configs)} presets",
                  flush=True)
            samples = harness.sweep(configs, prepare, step, args.warmup, args.reps, record=record)
            summary = lib.summarize_samples(samples)
            record.set_summary(f"L{ctx_len}", summary)

            for cfg in configs:
                preset = cfg["preset"]
                median_gpu = summary[cfg["key"]]["gpu_ms"]["median"]
                median_wall = summary[cfg["key"]]["wall_ms"]["median"]
                total_bytes = infos[preset]["param_bytes"]["total"]
                # Flat, gpu-time based, and carrying the grid coordinates. S2/S3/S5 all
                # publish this shape so analyze_latency can fit across scenarios; an
                # earlier nested-only version here left the decode fit with zero rows.
                entry = lib.derived_metrics(specs[preset], widths[preset], total_bytes,
                                            peaks, median_gpu, 1, 1, ctx_len)
                entry["alpha_ms"] = summary[cfg["key"]]["alpha_ms"]["median"]
                entry["batch"] = 1
                entry["ctx_len"] = ctx_len
                entry["tokens_per_step"] = 1
                entry["decode_tok_s"] = 1.0 / (median_gpu / 1000.0) if median_gpu else None
                entry["wall_achieved_bw_gbps"] = lib.derived_metrics(
                    specs[preset], widths[preset], total_bytes, peaks, median_wall, 1, 1,
                    ctx_len)["achieved_bw_gbps"]
                derived_all[cfg["key"]] = entry
            record.set_extra("derived", derived_all)

            baseline = "large" if "large" in presets else presets[-1]
            for metric in ("wall_ms", "gpu_ms"):
                for preset in presets:
                    if preset == baseline:
                        continue
                    key = f"L{ctx_len}/{preset}_vs_{baseline}/{metric}"
                    record.set_comparison(key, lib.compare_pairs(
                        samples, f"{baseline}_L{ctx_len}", f"{preset}_L{ctx_len}", metric=metric,
                        seed=args.seed))
            for metric in ("wall_ms", "gpu_ms"):
                verdict = record.data["comparisons"][f"L{ctx_len}/{presets[0]}_vs_{baseline}/{metric}"]
                print(f"[s1]   L={ctx_len:<5} {metric:<8} speedup={verdict['speedup']:.4f} "
                      f"ci=[{verdict['ratio_lo']:.3f},{verdict['ratio_hi']:.3f}] "
                      f"mdd={verdict['mdd_pct']:.1f}% -> {verdict['verdict']}", flush=True)

        record.set_extra("clocks_at_end", lib.clocks_snapshot())
        record.set_extra("peak_memory", lib.peak_memory_snapshot())

    record.complete()
    print("PASS s1_decode_step", flush=True)


if __name__ == "__main__":
    main()

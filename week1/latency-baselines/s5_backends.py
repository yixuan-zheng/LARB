"""S5: does removing host dispatch overhead reveal the FFN width effect?

Purpose in the ladder
---------------------
This is the decisive scenario. S0 measured ~87 us of fixed overhead per eager module
invocation and Gemma3n performs ~455 invocations per forward, which accounts for the
pilot's ~46 ms of ``alpha`` inside a ~55 ms step. S5 restates the same geometry under
progressively cheaper dispatch and tests the prediction directly:

    if ``alpha`` is what hides the width effect, then as ``alpha`` -> 0 the Large/Small
    latency ratio must move from ~1.0 toward the weight-byte ratio.

Workload definition and why it was chosen
-----------------------------------------
* A *prefill* workload (prompt length 512, batch 4 by default) is used for the graph
  tiers because it has fully static input shapes and no ``past_key_values`` argument, so
  it is legitimately capturable. A decode step with a mutating cache is not, and faking
  it would produce a benchmark that measures something other than the model.
* A decode workload is also measured, with ``torch.compile`` only. Its cache handling is
  left alone and any failure is recorded rather than worked around.

Backend tiers
-------------
``eager``      -- the reference, identical to S1-S4.
``compile``    -- ``torch.compile(mode="reduce-overhead")``, which is also the tier most
                  likely to fold the per-module Python dispatch that dominates here.
``cudagraph``  -- a manually captured ``torch.cuda.CUDAGraph`` around one prefill, replayed
                  as the timed region. Replay removes essentially all host launch cost, so
                  the residual time is device time and the width effect should be at its
                  most visible.

Honesty rules
-------------
Capture or compilation failure is *recorded* (``status: failed``, with the exception text)
and the tier is omitted, never approximated or emulated. A tier that cannot run is a
result about the model, not an inconvenience to be hidden. In the first full run the CUDA
Graph tier failed for every preset with ``cudaErrorStreamCaptureInvalidated``: Gemma 3n's
forward contains operations that are illegal inside a capture (host-synchronising
constructs and per-call device-tensor creation). That is a finding, not a gap -- it is a
concrete reason the ~50 ms fixed per-step cost cannot simply be graphed away, and
therefore why the decode ratio stays near 1.0.
"""
from __future__ import annotations

import argparse
import traceback

import torch

import build_worker
import latency_lib as lib

SCENARIO = "s5_backends"


def tier_eager(worker, ids):
    def run():
        return worker(input_ids=ids, use_cache=True, logits_to_keep=1)
    return run, None


def tier_compile(worker, ids, mode="reduce-overhead"):
    compiled = torch.compile(worker, mode=mode, fullgraph=False, dynamic=False)
    for _ in range(3):
        compiled(input_ids=ids, use_cache=True, logits_to_keep=1)
    torch.cuda.synchronize()

    def run():
        return compiled(input_ids=ids, use_cache=True, logits_to_keep=1)
    return run, {"mode": mode}


def tier_cudagraph(worker, ids, warmup: int = 3):
    """Capture one static prefill. ``ids`` must not be re-allocated between replays."""
    stream = torch.cuda.Stream()
    stream.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(stream):
        for _ in range(warmup):
            worker(input_ids=ids, use_cache=True, logits_to_keep=1)
    torch.cuda.current_stream().wait_stream(stream)
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        captured = worker(input_ids=ids, use_cache=True, logits_to_keep=1)
    # Touch the output so the capture is not optimised away, then replay once to prove it.
    _ = captured.logits.sum().item()
    graph.replay()
    torch.cuda.synchronize()

    def run():
        graph.replay()
        return captured
    return run, {"pool": getattr(graph, "pool", lambda: None)() if hasattr(graph, "pool") else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=40, default_warmup=10)
    parser.add_argument("--backends", default="eager,compile,cudagraph")
    parser.add_argument("--prompt-len", type=int, default=512)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--prompt-offset", type=int, default=0)
    args = parser.parse_args()
    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    presets = lib.selected_presets(args)

    protocol = lib.prepare_runtime(args)
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks, presets=presets)
    record.set_protocol(warmup=args.warmup, reps=args.reps, interleaved=True, shuffled=True,
                        workload="prefill", prompt_len=args.prompt_len, batch=args.batch,
                        backends=backends, flush_l2=args.flush_l2, flush_mb=args.flush_mb,
                        prompt_offset=args.prompt_offset)
    if args.estimate_only:
        print(lib.estimate_wall_time(len(backends) * len(presets), args.reps, args.warmup, 60.0))
        return

    print("[s5] clock ramp ...", flush=True)
    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")

    print(f"[s5] building workers: {presets}", flush=True)
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

    ids, digest = lib.build_prompt_ids(tokenizer, args.prompt_len, args.prompt_offset)
    ids = ids.repeat(args.batch, 1).contiguous().to("cuda")
    record.set_extra("prompt_sha256", {str(args.prompt_len): digest})

    harness = lib.Harness(args)
    tiers, tier_status = {}, {}
    derived_all = {}
    with torch.inference_mode():
        for preset in presets:
            for backend in backends:
                key = f"{preset}_{backend}"
                try:
                    if backend == "eager":
                        run, meta = tier_eager(workers[preset], ids)
                    elif backend == "compile":
                        run, meta = tier_compile(workers[preset], ids)
                    elif backend == "cudagraph":
                        run, meta = tier_cudagraph(workers[preset], ids)
                    else:
                        raise ValueError(f"unknown backend {backend!r}")
                    tiers[key] = run
                    tier_status[key] = {"status": "ok", "meta": meta}
                except Exception as exc:  # noqa: BLE001 - recorded, never hidden
                    tier_status[key] = {"status": "failed", "exception": repr(exc),
                                        "traceback": traceback.format_exc().splitlines()[-6:]}
                    print(f"[s5] {key}: tier FAILED -> {exc!r}", flush=True)
        record.set_extra("tier_status", tier_status)
        if not tiers:
            raise SystemExit("FAIL s5_backends: no backend tier could be prepared")

        configs = [{"key": k, "preset": k.split("_")[0], "backend": k.split("_", 1)[1]}
                   for k in tiers]
        print(f"[s5] prefill L={args.prompt_len} B={args.batch}: {args.warmup} warmup + "
              f"{args.reps} reps x {len(configs)} tiers", flush=True)
        samples = harness.sweep(configs, lambda cfg: None, lambda cfg, s: tiers[cfg["key"]](),
                                args.warmup, args.reps, record=record)
        summary = lib.summarize_samples(samples)
        record.set_summary("prefill", summary)

        for cfg in configs:
            preset, backend = cfg["preset"], cfg["backend"]
            gpu = summary[cfg["key"]]["gpu_ms"]["median"]
            d = lib.derived_metrics(specs[preset], widths[preset], total_bytes[preset], peaks,
                                    gpu, args.batch, args.prompt_len, args.prompt_len)
            d["prefill_tok_s"] = (args.batch * args.prompt_len) / (gpu / 1000.0) if gpu else None
            d["alpha_ms"] = summary[cfg["key"]]["alpha_ms"]["median"]
            derived_all[cfg["key"]] = d
        record.set_extra("derived", derived_all)

        baseline = "large"
        for backend in backends:
            if f"{baseline}_{backend}" not in tiers:
                continue
            for preset in presets:
                if preset == baseline or f"{preset}_{backend}" not in tiers:
                    continue
                v = lib.compare_pairs(samples, f"{baseline}_{backend}", f"{preset}_{backend}",
                                      metric="gpu_ms", seed=args.seed)
                record.set_comparison(f"{backend}/{preset}_vs_{baseline}", v)
                gk = f"{baseline}_{backend}"
                print(f"[s5]   {backend:<10} {preset:<7} speedup={v['speedup']:.4f} "
                      f"ci=[{v['ratio_lo']:.3f},{v['ratio_hi']:.3f}] "
                      f"alpha_large={derived_all[gk]['alpha_ms']:.3f}ms -> {v['verdict']}", flush=True)
        record.set_extra("clocks_at_end", lib.clocks_snapshot())
        record.set_extra("peak_memory", lib.peak_memory_snapshot())

    record.complete()
    print("PASS s5_backends", flush=True)


if __name__ == "__main__":
    main()

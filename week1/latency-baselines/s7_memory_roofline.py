"""S7: memory, capacity and roofline utilization for one preset.

Purpose in the ladder
---------------------
The latency story may turn out to be flat, but the memory story is arithmetically
certain: the FFN weight footprint falls from 7.05 GiB (large) to 5.03 GiB (small), and
that capacity is fungible -- it buys batch, context, or a second co-resident model. S7
quantifies it, and simultaneously answers "are we anywhere near the roofline?", which is
the context needed to interpret every latency number in the rest of the suite.

What is measured
----------------
* Exact resident weights per component bucket (embeddings, per-layer embeddings, FFN,
  attention, AltUp, Laurel, per-layer input, norms), measured off the live module, and
  compared against the analytic prediction from ``latency_math``. The delta is reported,
  so a model-vs-reality mismatch is visible rather than averaged away.
* Peak VRAM after load and during a prefill/decode grid point.
* Cache footprint per token, measured off the live cache object rather than assumed.
* Maximum batch before OOM at a short and a long context, by doubling until an
  allocation fails. This is the concrete capacity comparison across presets.
* Achieved bandwidth and MFU for one representative step, expressed as a fraction of the
  device roof (L40S: 864 GB/s, 362 TFLOPS bf16 dense).

Run one preset per process (``run_suite.sh`` does this) so peak-VRAM figures are not
polluted by other presets' weights.
"""
from __future__ import annotations

import argparse
import csv
import json

import torch

import build_worker
import latency_lib as lib
import latency_math as lm

SCENARIO = "s7_memory_roofline"


def cache_bytes(cache) -> dict:
    """Measured KV footprint from the live cache tensors (not an assumption)."""
    total, layers_seen = 0, 0
    for attr_name in ("layers",):
        layers = getattr(cache, attr_name, None)
        if not layers:
            continue
        for layer in layers:
            found = False
            for field in ("keys", "values", "key_cache", "value_cache"):
                tensor = getattr(layer, field, None)
                if isinstance(tensor, torch.Tensor):
                    total += tensor.numel() * tensor.element_size()
                    found = True
            if found:
                layers_seen += 1
    return {"measured_bytes": total, "cache_layer_entries": layers_seen}


def max_batch_before_oom(worker, ids_fn, start: int = 1, cap: int = 512) -> dict:
    """Double the batch until an allocation fails; return the last success."""
    last_ok, failure = 0, None
    batch = start
    while batch <= cap:
        torch.cuda.empty_cache()
        try:
            ids = ids_fn(batch)
            with torch.inference_mode():
                out = worker(input_ids=ids, use_cache=True, logits_to_keep=1)
            del out
            torch.cuda.empty_cache()
            last_ok = batch
            batch *= 2
        except torch.cuda.OutOfMemoryError as exc:
            failure = repr(exc).splitlines()[0] if str(exc) else "OutOfMemoryError"
            break
        except RuntimeError as exc:
            failure = repr(exc)[:200]
            break
    return {"max_batch": last_ok, "first_failing_batch": batch, "failure": failure}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=10, default_warmup=3)
    parser.add_argument("--prefill-len", type=int, default=2048)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--capacity-contexts", default="1,2048")
    parser.add_argument("--prompt-offset", type=int, default=0)
    parser.add_argument("--capacity-cap", type=int, default=64,
                        help="stop doubling the capacity batch at this size")
    args = parser.parse_args()
    if not args.preset:
        args.preset = "large"
    capacity_contexts = [int(x) for x in args.capacity_contexts.split(",") if x.strip()]

    protocol = lib.prepare_runtime(args)
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks)
    record.set_protocol(warmup=args.warmup, reps=args.reps, prefill_len=args.prefill_len,
                        batch=args.batch, capacity_contexts=capacity_contexts,
                        one_preset_per_process=True, flush_l2=args.flush_l2,
                        prompt_offset=args.prompt_offset)
    if args.estimate_only:
        print(lib.estimate_wall_time(3, args.reps, args.warmup, 300.0))
        return

    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")

    print(f"[s7] building worker: {args.preset}", flush=True)
    worker, tokenizer, info = build_worker.build_worker(args.preset, lib.dtype_of(args))
    lib.reset_peak_memory()
    spec = lib.arch_spec_from_config(worker.config, model=worker)
    widths = list(spec.widths)
    dtype_bytes = lib.DTYPE_BYTES[args.dtype]

    analytic_weights = lm.weight_bytes(spec, widths, dtype_bytes)
    measured = info["param_bytes"]
    memory = {
        "measured_bytes": measured, "analytic_bytes": analytic_weights,
        "measured_total_gib": measured["total"] / 1024**3,
        "analytic_total_gib": analytic_weights["total"] / 1024**3,
        "analytic_minus_measured_bytes": analytic_weights["total"] - measured["total"],
        "analytic_minus_measured_pct": 100.0 * (analytic_weights["total"] - measured["total"])
                                     / measured["total"],
        "widths": widths,
        "narrow_ffn_layers": sum(1 for w in widths if w < 16384),
    }
    if info["peak_after_load"] if "peak_after_load" in info else True:
        memory["peak_after_load"] = lib.peak_memory_snapshot()
    record.set_extra("memory", memory)
    print(f"[s7] weights: measured={memory['measured_total_gib']:.2f} GiB "
          f"analytic={memory['analytic_total_gib']:.2f} GiB "
          f"delta={memory['analytic_minus_measured_pct']:+.1f}%", flush=True)

    harness = lib.Harness(args)
    with torch.inference_mode():
        base, digest = lib.build_prompt_ids(tokenizer, min(args.prefill_len, 512), args.prompt_offset)
        record.set_extra("prompt_sha256", {str(min(args.prefill_len, 512)): digest})

        # --- cache footprint per token, measured --------------------------------- #
        cache_report = {}
        for ctx_len in [c for c in capacity_contexts if c >= 1]:
            probe_len = max(1, min(ctx_len, args.prefill_len))
            ids, _ = lib.build_prompt_ids(tokenizer, probe_len, args.prompt_offset)
            cache = worker(input_ids=ids.to("cuda"), use_cache=True,
                           logits_to_keep=1).past_key_values
            measured_cache = cache_bytes(cache)
            measured_cache["context_tokens"] = probe_len
            measured_cache["bytes_per_token"] = (measured_cache["measured_bytes"] / probe_len)
            measured_cache["analytic_bytes"] = lm.kv_resident_bytes(spec, probe_len, 1, dtype_bytes)
            cache_report[str(ctx_len)] = measured_cache
            del cache
            torch.cuda.empty_cache()
        record.set_extra("kv_cache", cache_report)

        # --- roofline for one representative point -------------------------------- #
        ids, _ = lib.build_prompt_ids(tokenizer, args.prefill_len, args.prompt_offset)
        ids = ids.repeat(args.batch, 1).contiguous().to("cuda")
        one_id = lib.next_token_id(tokenizer, args.prompt_offset).repeat(args.batch, 1).to("cuda")

        def prefill():
            return worker(input_ids=ids, use_cache=True, logits_to_keep=1)

        configs = [{"key": "prefill"}, {"key": "decode"}]
        states = {"prefill": None}

        def prepare(cfg):
            if cfg["key"] == "decode":
                return prefill().past_key_values
            return None

        def step(cfg, state):
            if cfg["key"] == "prefill":
                return prefill()
            return worker(input_ids=one_id, past_key_values=state, use_cache=True,
                          logits_to_keep=1)

        samples = harness.sweep(configs, prepare, step, args.warmup, args.reps, record=record)
        summary = lib.summarize_samples(samples)
        record.set_summary("roofline_point", summary)
        roofline = {}
        for cfg in configs:
            key = cfg["key"]
            gpu = summary[key]["gpu_ms"]["median"]
            q_len, ctx_len = (args.prefill_len, args.prefill_len) if key == "prefill" else (1, args.prefill_len)
            kv = 0 if key == "prefill" else lm.kv_resident_bytes(spec, ctx_len, args.batch, dtype_bytes)
            d = lib.derived_metrics(spec, widths, measured["total"], peaks, gpu, args.batch,
                                    q_len, ctx_len, kv_bytes=kv)
            d["gpu_ms"] = gpu
            d["alpha_ms"] = summary[key]["alpha_ms"]["median"]
            roofline[key] = d
        record.set_extra("roofline", roofline)

        # --- capacity: maximum batch before OOM ----------------------------------- #
        capacity = {}
        for ctx_len in capacity_contexts:
            base_ids, _ = lib.build_prompt_ids(tokenizer, max(1, ctx_len), args.prompt_offset)
            capacity[str(ctx_len)] = max_batch_before_oom(
                worker, lambda b, i=base_ids: i.repeat(b, 1).contiguous().to("cuda"),
                cap=args.capacity_cap)
            print(f"[s7] max batch at ctx={ctx_len}: {capacity[str(ctx_len)]['max_batch']}", flush=True)
        record.set_extra("capacity", capacity)

        record.set_extra("clocks_at_end", lib.clocks_snapshot())
        record.set_extra("peak_memory", lib.peak_memory_snapshot())

    # CSV companion so the profile can be plotted without extra dependencies.
    csv_path = lib.RESULTS / f"s7_memory_{args.preset}.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["preset", "bucket", "bytes", "gib"])
        for bucket, size in sorted(measured.items()):
            writer.writerow([args.preset, bucket, size, round(size / 1024**3, 4)])
    record.set_extra("csv", str(csv_path))
    record.complete()
    print("PASS s7_memory_roofline", flush=True)


if __name__ == "__main__":
    main()

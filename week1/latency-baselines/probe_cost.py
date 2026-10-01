"""Measure the real per-configuration cost so scenario grids can be sized from data.

Why this exists
---------------
Scenario grids sized on an optimistic estimate can exhaust their own timeout cap, which
wastes a finite allocation without producing a comparison. This probe reports per-iteration
cost for a candidate grid using the *same* harness as the scenarios (same clock ramp, same
flush, same dual-clock timer), so the numbers transfer directly into ``--reps`` choices.

It reports three things per configuration: the median prefill, the median single decode
step, and the total seconds per sweep iteration (prefill + flush + decode), which is the
quantity that multiplies into a scenario's wall time.

Usage
-----
    python probe_cost.py --presets large --lengths 128,512,2048 --batches 1,4 --reps 3
"""
from __future__ import annotations

import argparse

import torch

import build_worker
import latency_lib as lib

SCENARIO = "probe_cost"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=3, default_warmup=1)
    parser.add_argument("--lengths", default="128,512,2048")
    parser.add_argument("--batches", default="1,4")
    args = parser.parse_args()
    lengths = [int(x) for x in args.lengths.split(",") if x.strip()]
    batches = [int(x) for x in args.batches.split(",") if x.strip()]
    presets = lib.selected_presets(args)

    lib.prepare_runtime(args)
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_protocol(reps=args.reps, warmup=args.warmup, lengths=lengths, batches=batches)
    lib.clock_ramp(args.clock_ramp_s)
    lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    workers, tokenizer, infos = build_worker.build_workers(presets, lib.dtype_of(args))
    lib.reset_peak_memory()
    harness = lib.Harness(args)
    one_id = lib.next_token_id(tokenizer).to("cuda")

    rows = []
    with torch.inference_mode():
        for preset in presets:
            worker = workers[preset]
            for length in lengths:
                base, digest = lib.build_prompt_ids(tokenizer, length)
                for batch in batches:
                    ids = base.repeat(batch, 1).contiguous().to("cuda")
                    token = one_id.repeat(batch, 1)
                    prefill_ms, decode_ms = [], []
                    for _ in range(args.warmup + args.reps):
                        out, wall_p, gpu_p = harness.timer.time(
                            lambda: worker(input_ids=ids, use_cache=True, logits_to_keep=1))
                        cache = out.past_key_values
                        _, wall_d, gpu_d = harness.timer.time(
                            lambda: worker(input_ids=token, past_key_values=cache,
                                           use_cache=True, logits_to_keep=1))
                        prefill_ms.append(gpu_p)
                        decode_ms.append(gpu_d)
                    prefill_ms = sorted(prefill_ms)[len(prefill_ms) // 2:]
                    decode_ms = sorted(decode_ms)[len(decode_ms) // 2:]
                    p50p, p50d = prefill_ms[0], decode_ms[0]
                    rows.append({"preset": preset, "length": length, "batch": batch,
                                 "tokens": length * batch, "prompt_sha256": digest,
                                 "prefill_gpu_ms": p50p, "decode_gpu_ms": p50d,
                                 "seconds_per_iteration": (p50p + p50d) / 1000.0})
                    record.add_sample(rows[-1])
                    print(f"{preset:<7} L={length:<5} B={batch:<3} tokens={length * batch:<6} "
                          f"prefill={p50p:9.2f}ms decode={p50d:8.2f}ms "
                          f"iter={rows[-1]['seconds_per_iteration']:.3f}s", flush=True)
        record.set_extra("rows", rows)
        record.set_extra("peak_memory", lib.peak_memory_snapshot())
    record.complete()
    print("PASS probe_cost", flush=True)


if __name__ == "__main__":
    main()

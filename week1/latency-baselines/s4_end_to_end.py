"""S4: end-to-end generation: TTFT, inter-token latency, total latency and throughput.

Purpose in the ladder
---------------------
S1-S3 measure single phases. S4 integrates them into the numbers a reader would actually
quote: time to first token, the distribution of inter-token latencies over a real
generation, end-to-end time and tokens/second, all against peak VRAM.

Workload definition and why it was chosen
-----------------------------------------
* Prompt lengths 128 / 1024 tokens; batch sizes 1 / 8.
* A fixed 128 generated tokens per request, produced by a manual greedy loop that runs
  exactly ``new_tokens`` steps regardless of EOS. This is deliberate: an early EOS would
  silently shorten some configurations and make latencies incomparable, which is the kind
  of confound the pilot was careful to avoid by using teacher forcing. Fixing the length
  is the equivalent guarantee here, and it is stated rather than assumed.
* Manual loop rather than ``generate`` so that the prefill, the first step and the
  remaining steps are timed separately with the same instrument.

Metrics per configuration
-------------------------
* ``ttft_ms``      = prefill + first decode step (time to first generated token).
* ``itl_ms``       = median and p90 of the 127 steady-state steps (first step excluded).
* ``e2e_ms``       = the whole loop, wall clock.
* ``decode_tok_s`` = batch / median ITL; ``e2e_tok_s`` = batch * new_tokens / e2e.
* peak VRAM across the run.

Repetitions here are full generations, which makes this the most expensive scenario; the
per-step samples of the single generation are retained as the distribution rather than
repeating the whole generation many times.
"""
from __future__ import annotations

import argparse

import torch

import build_worker
import latency_lib as lib
import latency_math as lm

SCENARIO = "s4_end_to_end"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=3, default_warmup=1)
    parser.add_argument("--prompt-lengths", default="128,1024")
    parser.add_argument("--batch-sizes", default="1,8")
    parser.add_argument("--new-tokens", type=int, default=128)
    parser.add_argument("--prompt-offset", type=int, default=0)
    args = parser.parse_args()
    prompt_lengths = [int(x) for x in args.prompt_lengths.split(",") if x.strip()]
    batch_sizes = [int(x) for x in args.batch_sizes.split(",") if x.strip()]
    presets = lib.selected_presets(args)

    protocol = lib.prepare_runtime(args)
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks, presets=presets)
    record.set_protocol(warmup=args.warmup, reps=args.reps, interleaved=False,
                        note="generations are full loops; the per-step distribution is the sample set",
                        new_tokens=args.new_tokens, greedy=True, eos_ignored=True,
                        prompt_lengths=prompt_lengths, batch_sizes=batch_sizes,
                        flush_l2=args.flush_l2, flush_mb=args.flush_mb,
                        prompt_offset=args.prompt_offset)
    if args.estimate_only:
        print(lib.estimate_wall_time(len(prompt_lengths) * len(batch_sizes) * len(presets),
                                     args.reps, args.warmup, 1000.0 * (args.new_tokens / 8)))
        return

    print("[s4] clock ramp ...", flush=True)
    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")

    print(f"[s4] building workers: {presets}", flush=True)
    workers, tokenizer, infos = build_worker.build_workers(presets, lib.dtype_of(args))
    lib.reset_peak_memory()
    specs, widths, total_bytes = {}, {}, {}
    for preset in presets:
        spec = lib.arch_spec_from_config(workers[preset].config)
        specs[preset], widths[preset] = spec, list(spec.widths)
        total_bytes[preset] = infos[preset]["param_bytes"]["total"]
    record.set_extra("workers", infos)

    prompts, hashes = {}, {}
    for prompt_len in prompt_lengths:
        ids, digest = lib.build_prompt_ids(tokenizer, prompt_len, args.prompt_offset)
        prompts[prompt_len] = ids.to("cuda")
        hashes[str(prompt_len)] = digest
    record.set_extra("prompt_sha256", hashes)

    harness = lib.Harness(args)
    dtype_bytes = lib.DTYPE_BYTES[args.dtype]
    derived_all, comparisons = {}, {}

    with torch.inference_mode():
        for prompt_len in prompt_lengths:
            for batch in batch_sizes:
                grid_key = f"L{prompt_len}_B{batch}"
                runnable = [p for p in presets
                            if lib.vram_budget_check(specs[p], widths[p], batch, prompt_len,
                                                     dtype_bytes, fraction=0.5)["ok"]]
                if not runnable:
                    print(f"[s4] {grid_key}: SKIPPED (VRAM budget)", flush=True)
                    continue
                prompt = prompts[prompt_len].repeat(len(runnable), 1).contiguous()
                print(f"[s4] {grid_key}: {len(runnable)} presets x {args.reps} generations "
                      f"x {args.new_tokens} tokens", flush=True)
                for preset in runnable:
                    worker = workers[preset]
                    runs = []
                    for rep in range(args.reps + args.warmup):
                        harness.flush()
                        # One timed prefill that also yields the cache: the previous
                        # version prefilled twice, which doubled work and measured a
                        # cache it then discarded.
                        prefill_out, prefill_wall, prefill_gpu = harness.timer.time(
                            lambda: worker(input_ids=prompt, use_cache=True, logits_to_keep=1))
                        cache = prefill_out.past_key_values
                        step_input = prompt[:, -1:]
                        first_wall, step_walls, e2e = None, [], 0.0
                        for step_index in range(args.new_tokens):
                            # A real greedy loop: feed the argmax of this step into the
                            # next one, so the decode distribution is the genuine
                            # autoregressive one rather than a repeated token.
                            step_out, wall, gpu = harness.timer.time(
                                lambda c=cache, n=step_input: worker(input_ids=n,
                                                                    past_key_values=c,
                                                                    use_cache=True,
                                                                    logits_to_keep=1))
                            if step_index == 0:
                                first_wall = wall
                            else:
                                step_walls.append(wall)
                            e2e += wall
                            step_input = step_out.logits[:, -1:].argmax(-1)
                            cache = step_out.past_key_values
                        if rep >= args.warmup:
                            runs.append({"prefill_wall_ms": prefill_wall,
                                         "prefill_gpu_ms": prefill_gpu,
                                         "ttft_ms": prefill_wall + (first_wall or 0.0),
                                         "itl_wall_ms": step_walls,
                                         "e2e_ms": prefill_wall + e2e})
                    itl = sorted(v for run in runs for v in run["itl_wall_ms"])
                    ttft = [run["ttft_ms"] for run in runs]
                    e2e = [run["e2e_ms"] for run in runs]
                    entry = {"preset": preset, "batch": batch, "prompt_len": prompt_len,
                             "new_tokens": args.new_tokens, "generations": len(runs),
                             "ttft_ms": lm.summarize(ttft), "e2e_ms": lm.summarize(e2e),
                             "itl_ms": lm.summarize(itl) if itl else None,
                             "prefill_ms": lm.summarize([r["prefill_wall_ms"] for r in runs])}
                    gpu_itl = None
                    entry["decode_tok_s"] = (batch / (entry["itl_ms"]["median"] / 1000.0)
                                             if entry["itl_ms"] else None)
                    entry["e2e_tok_s"] = (batch * args.new_tokens /
                                          (entry["e2e_ms"]["median"] / 1000.0))
                    entry["per_step_wall_ms"] = [round(v, 4) for v in itl]
                    derived_all[f"{preset}_{grid_key}"] = entry
                    record.set_extra("derived", derived_all)
                    print(f"[s4]   {grid_key:<12} {preset:<7} ttft={entry['ttft_ms']['median']:.1f}ms "
                          f"itl_p50={entry['itl_ms']['median']:.2f}ms "
                          f"itl_p90={entry['itl_ms']['p90']:.2f}ms "
                          f"e2e={entry['e2e_ms']['median']:.0f}ms "
                          f"tok_s={entry['e2e_tok_s']:.1f}", flush=True)
                for baseline in ["large"] if "large" in runnable else runnable[-1:]:
                    for preset in runnable:
                        if preset == baseline:
                            continue
                        left = derived_all[f"{baseline}_{grid_key}"]["per_step_wall_ms"]
                        right = derived_all[f"{preset}_{grid_key}"]["per_step_wall_ms"]
                        n = min(len(left), len(right))
                        comparisons[f"{grid_key}/{preset}_vs_{baseline}/itl"] = {
                            "metric": "itl_wall_ms", "large_key": baseline, "small_key": preset,
                            **lm.paired_stats(left[:n], right[:n], seed=args.seed)}
                record.set_extra("itl_comparisons", comparisons)

        record.set_extra("clocks_at_end", lib.clocks_snapshot())
        record.set_extra("peak_memory", lib.peak_memory_snapshot())

    record.complete()
    print("PASS s4_end_to_end", flush=True)


if __name__ == "__main__":
    main()

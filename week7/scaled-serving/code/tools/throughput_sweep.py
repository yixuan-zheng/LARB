#!/usr/bin/env python3
"""P1 Gate C: concurrency and throughput sweep on the real engine.

Runs fixed-length generations (thinking + answer tokens) at offered
concurrency 1..32 through the same engine configuration as the main rig.
Each point keeps exactly `concurrency` requests in flight for
`seconds_per_point`; throughput is completed output tokens divided by the
measured wall time. Records GPU utilisation/memory at 1 Hz and scheduler
preemptions from the audit stream.
"""
import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from larb_scaled import config  # noqa: E402

PROMPT = ("Solve the following competition problem carefully and put the final "
          "answer in a boxed expression. Compute 17 + 23 + 41 + 59 modulo 7, "
          "then multiply the result by 3 and subtract 5. Explain every step "
          "before the final answer.")


def gpu_sampler(stop, rows):
    while not stop.is_set():
        try:
            text = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5).stdout.strip().splitlines()[0]
            memory, util = [float(part) for part in text.split(",")[:2]]
            rows.append(dict(monotonic=time.monotonic(), memory_mib=memory, util=util))
        except Exception:
            pass
        stop.wait(1.0)


def read_preemption(out, after):
    peak = 0
    path = Path(out) / "scheduler.jsonl"
    if not path.exists():
        return None
    with path.open() as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("monotonic", 0) >= after:
                peak = max(peak, int(row.get("preemption_total") or 0))
    return peak


def percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values) - 1, int(fraction * (len(values) - 1)))] if values else None


async def one_request(llm, params_cls, prompt_ids, tokens, tag, seed):
    params = params_cls(max_tokens=tokens, min_tokens=tokens, ignore_eos=True,
                        temperature=0.6, top_p=0.95, top_k=20, seed=seed,
                        skip_special_tokens=False)
    start = time.monotonic()
    produced = 0
    async for output in llm.generate({"prompt_token_ids": prompt_ids}, params,
                                     request_id=f"{tag}-{seed}"):
        produced = len(output.outputs[0].token_ids)
    return dict(start=start, end=time.monotonic(), tokens=produced)



async def run_point(llm, params_cls, prompt_ids, concurrency, tokens, seconds, seed_base):
    finished = []
    counter = [0]

    async def tracked(tag, seed):
        result = await one_request(llm, params_cls, prompt_ids, tokens, tag, seed)
        finished.append(result)
        return result

    inflight = set()

    def launch():
        counter[0] += 1
        task = asyncio.create_task(tracked(
            f"c{concurrency}-t{tokens}-{counter[0]}", seed_base + counter[0]))
        inflight.add(task)
        task.add_done_callback(inflight.discard)
        return task

    # Warm-up: one full batch to the same length, then let it drain.
    await asyncio.gather(*(launch() for _ in range(concurrency)))
    started = time.monotonic()
    stop_at = started + seconds
    while time.monotonic() < stop_at:
        while len(inflight) < concurrency:
            launch()
        await asyncio.sleep(0.02)
    if inflight:
        await asyncio.gather(*inflight, return_exceptions=True)
    ended = time.monotonic()
    # Only requests started inside the measured window count toward throughput.
    measured = [row for row in finished if row["start"] >= started]
    return measured, ended - started


async def sweep(args, out, results=None):
    from vllm import SamplingParams
    from vllm.engine.arg_utils import AsyncEngineArgs
    from vllm.v1.engine.async_llm import AsyncLLM
    from transformers import AutoTokenizer

    protocol = config.load_protocol()
    model = os.environ.get("LARB_MODEL_PATH", protocol["model"]["local_path_default"])
    engine_args = AsyncEngineArgs(
        model=model, dtype=protocol["model"]["dtype"],
        max_model_len=protocol["engine"]["max_model_len"],
        max_num_seqs=args.max_num_seqs,
        max_num_batched_tokens=protocol["engine"]["max_num_batched_tokens"],
        gpu_memory_utilization=args.gpu_util,
        enforce_eager=args.eager,
        enable_prefix_caching=False,
        seed=protocol["seeding"]["seed_base"],
        logits_processors=["larb_scaled.controller:PressureProcessor"],
        scheduler_cls="larb_scaled.controller.QueueAuditScheduler",
        disable_log_stats=True, generation_config="vllm",
    )
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    prompt_ids = tokenizer.encode(PROMPT, add_special_tokens=False)
    llm = AsyncLLM.from_engine_args(engine_args)
    if results is None:
        results = dict(eager=args.eager, max_num_seqs=args.max_num_seqs,
                       prompt_tokens=len(prompt_ids), points=[])
    results.setdefault("points", [])
    for tokens in args.thinking:
        for concurrency in args.concurrency:
            if concurrency > args.max_num_seqs:
                continue
            total = tokens + args.answer_tokens
            print(f"[sweep] concurrency={concurrency} tokens={total} seconds={args.seconds}",
                  flush=True)
            stop = threading.Event()
            gpu_rows = []
            sampler = threading.Thread(target=gpu_sampler, args=(stop, gpu_rows), daemon=True)
            sampler.start()
            point_start = time.monotonic()
            try:
                finished, elapsed = await run_point(
                    llm, SamplingParams, prompt_ids, concurrency, total, args.seconds,
                    500000 + concurrency * 1000 + tokens)
            except Exception as exc:  # keep the earlier points if one point fails
                stop.set()
                results["points"].append(dict(concurrency=concurrency,
                                              thinking_tokens=tokens,
                                              error=repr(exc)))
                config.write_json(Path(out) / "throughput.json", results)
                print(f"[sweep] point failed: {exc!r}", flush=True)
                continue
            stop.set()
            sampler.join(timeout=3)
            produced = sum(row["tokens"] for row in finished)
            latencies = [row["end"] - row["start"] for row in finished]
            point = dict(concurrency=concurrency, thinking_tokens=tokens,
                         answer_tokens=args.answer_tokens, output_tokens_total=total,
                         requests=len(finished), elapsed_seconds=elapsed,
                         tokens=produced, output_tokens_per_second=produced / elapsed,
                         per_request_tokens_per_second=statistics.median(
                             [row["tokens"] / (row["end"] - row["start"])
                              for row in finished]) if finished else None,
                         latency_p50_s=percentile(latencies, 0.50),
                         latency_p90_s=percentile(latencies, 0.90),
                         gpu_memory_mib_mean=(statistics.mean([r["memory_mib"] for r in gpu_rows])
                                              if gpu_rows else None),
                         gpu_memory_mib_max=max([r["memory_mib"] for r in gpu_rows],
                                                default=None),
                         gpu_util_mean=(statistics.mean([r["util"] for r in gpu_rows])
                                        if gpu_rows else None),
                         preemption_peak=read_preemption(out, point_start))
            results["points"].append(point)
            config.write_json(Path(out) / "throughput.json", results)
            print(f"[sweep] -> {point['output_tokens_per_second']:.1f} tokens/s", flush=True)
            await asyncio.sleep(2)
    return results



def recommend(results, p2):
    points = {(p["concurrency"], p["thinking_tokens"]): p for p in results["points"]
              if p.get("output_tokens_per_second")}
    if not points:
        return dict(error="no usable points")
    four = {concurrency: point["output_tokens_per_second"]
            for (concurrency, tokens), point in points.items() if tokens == 4096}
    knee = max(four, key=four.get) if four else None
    candidates = sorted({concurrency for (concurrency, tokens) in points
                         if tokens == 4096 and (concurrency, 8192) in points}, reverse=True)
    if not candidates:
        best = max(points.values(), key=lambda point: point["output_tokens_per_second"])
        return dict(error="need a 4k and an 8k point at the same concurrency",
                    best_point=best, four_k_rates=four, knee_4k=knee)
    top = candidates[0]
    chosen_concurrency = (top if (knee is None or four.get(top, 0) >= 0.9 * four[knee])
                          else knee)
    if (chosen_concurrency, 8192) not in points:
        chosen_concurrency = top
    short = points[(chosen_concurrency, 4096)]
    long = points[(chosen_concurrency, 8192)]
    mid = short["output_tokens_per_second"] + 0.5 * (
        long["output_tokens_per_second"] - short["output_tokens_per_second"])
    planned_tokens = 63_000_000
    policy = p2["seed_reduction_policy"]
    if mid >= policy["4_seeds_min_tokens_per_second"]:
        seeds = 4
    elif mid >= policy["3_seeds_min_tokens_per_second"]:
        seeds = 3
    else:
        seeds = 2
    hours = planned_tokens * seeds / 4 / mid / 3600
    note = None
    if hours > 14.0:
        note = "does not fit one 16 h job at these seeds; split or reduce the cohort"
    elif mid < policy["2_seeds_min_tokens_per_second"]:
        note = ("below the ~1000 tokens/s planning point; the realised seed count "
                "is small, so the report must state the weaker resolution")
    return dict(concurrency=chosen_concurrency,
                rate_4k=short["output_tokens_per_second"],
                rate_8k=long["output_tokens_per_second"],
                rate_arm_average=mid, knee_4k=knee, four_k_rates=four,
                best_point=max(points.values(),
                               key=lambda point: point["output_tokens_per_second"]),
                planned_tokens=planned_tokens, seeds=seeds,
                hours_4seed=planned_tokens / mid / 3600,
                hours_at_seeds=hours, note=note)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4, 8, 16, 24, 32])
    parser.add_argument("--thinking", type=int, nargs="+", default=[4096])
    parser.add_argument("--answer-tokens", type=int, default=128)
    parser.add_argument("--seconds", type=float, default=300.0)
    parser.add_argument("--max-num-seqs", type=int, default=32)
    parser.add_argument("--gpu-util", type=float, default=0.85)
    parser.add_argument("--eager", action="store_true")
    parser.add_argument("--append", action="store_true",
                        help="append to an existing throughput.json (same engine mode)")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    os.environ["LARB_OUT"] = str(args.out)
    os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
    os.environ.setdefault("VLLM_USE_V1", "1")
    os.environ.setdefault("VLLM_ATTENTION_BACKEND", "FLASH_ATTN")
    os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    existing = None
    path = args.out / "throughput.json"
    if args.append and path.exists():
        existing = json.loads(path.read_text())
        existing["points"] = [point for point in existing.get("points", [])
                              if not point.get("error")]
        existing["eager"] = args.eager
    results = asyncio.run(sweep(args, args.out, existing))
    p2 = config.load_p2_main()
    results["recommendation"] = recommend(results, p2)
    config.write_json(args.out / "throughput.json", results)
    print(json.dumps(results["recommendation"], indent=2))


if __name__ == "__main__":
    main()

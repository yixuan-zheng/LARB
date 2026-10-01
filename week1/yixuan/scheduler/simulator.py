"""Deterministic, trace-driven Week 1 scheduling simulation (stdlib only)."""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path

PRESETS = ("large", "small")
PHASES = ("prefill", "decode", "transition_decode")


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


@dataclass
class Request:
    request_id: str
    arrival_ms: float
    prompt_tokens: int
    output_tokens: int  # replay truth; hidden from online policy
    estimated_output_tokens: int  # known at arrival to every policy
    prefill_end: float | None = None
    prefill_preset: str | None = None
    tokens: int = 0
    last_token_ms: float | None = None
    token_times: list[float] = field(default_factory=list)
    token_presets: list[str] = field(default_factory=list)
    switches: int = 0
    current_preset: str | None = None
    last_switch_token: int = 0

    @property
    def context_tokens(self):
        return self.prompt_tokens + self.tokens


class Latencies:
    """Median of per-step repeat costs; exact measured cells required by default."""

    def __init__(self, path, allow_nearest_example=False):
        self.cells = {}
        self.raw = read_csv(path)
        if not self.raw:
            raise ValueError("Empty latency table")
        self.example = all(r["run_id"] == "EXAMPLE_ONLY" for r in self.raw)
        self.allow_nearest_example = allow_nearest_example
        for r in self.raw:
            phase = r["phase"]
            if phase not in PHASES or r["preset"] not in PRESETS:
                raise ValueError(f"Unknown phase/preset: {r}")
            n = int(r["tokens_timed"])
            if n < 1 or (phase != "decode" and n != 1):
                raise ValueError("Invalid tokens_timed")
            if phase == "transition_decode" and (
                r["from_preset"],
                r["to_preset"],
            ) not in (("large", "small"), ("small", "large")):
                raise ValueError("Invalid transition direction")
            key = (
                phase,
                r["preset"],
                int(r["batch_size"]),
                int(r["context_tokens"]),
                r["from_preset"],
                r["to_preset"],
            )
            self.cells.setdefault(key, []).append(float(r["latency_ms"]) / n)

    def cost(self, phase, preset, batch, context, from_preset=""):
        to_preset = preset if phase == "transition_decode" else ""
        if phase != "transition_decode":
            from_preset = ""
        key = (phase, preset, batch, context, from_preset, to_preset)
        if key in self.cells:
            return statistics.median(self.cells[key]), (
                "EXAMPLE_ONLY" if self.example else "MEASURED"
            )
        if not (self.example and self.allow_nearest_example):
            raise ValueError(f"Missing latency cell {key}; no measured value invented")
        candidates = [
            k
            for k in self.cells
            if k[0] == phase
            and k[1] == preset
            and k[4] == from_preset
            and k[5] == to_preset
        ]
        if not candidates:
            raise ValueError(f"Missing latency phase/direction {key}")
        nearest = min(
            candidates, key=lambda k: (abs(k[2] - batch), abs(k[3] - context))
        )
        return (
            statistics.median(self.cells[nearest]),
            f"EXAMPLE_ONLY_NEAREST:{nearest[2]}:{nearest[3]}",
        )


def load_quality(path):
    records = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        schedule = r["schedule"]
        positions = [int(s["start_decode_token"]) for s in schedule]
        if not positions or positions[0] != 0 or positions != sorted(set(positions)):
            raise ValueError(
                "Quality schedule must start at zero and have increasing positions"
            )
        if any(s["preset"] not in PRESETS for s in schedule):
            raise ValueError("Unknown quality preset")
        records.append(r)
    return records


def load_trace(path):
    data = json.loads(Path(path).read_text())
    requests = [Request(**r) for r in data["requests"]]
    ids = [r.request_id for r in requests]
    if len(ids) != len(set(ids)) or any(
        r.arrival_ms < 0
        or r.prompt_tokens < 1
        or r.output_tokens < 1
        or r.estimated_output_tokens < 1
        for r in requests
    ):
        raise ValueError("Invalid trace requests")
    requests.sort(key=lambda r: (r.arrival_ms, r.request_id))
    return data["seed"], requests


def make_traces(outdir, seed=7):
    rng = random.Random(seed)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for pattern in ("steady", "burst", "changing_mix"):
        rows = []
        for i in range(18):
            arrival = (
                30 * i
                if pattern == "steady"
                else (0 if i < 12 else (i - 11) * 80) if pattern == "burst" else i * 25
            )
            prompt = (
                rng.choice([96, 128, 192])
                if pattern != "changing_mix" or i < 9
                else rng.choice([512, 768, 1024])
            )
            output = (
                rng.choice([8, 12, 16])
                if pattern != "changing_mix" or i < 9
                else rng.choice([20, 28, 36])
            )
            rows.append(
                dict(
                    request_id=f"{pattern}-{i:02d}",
                    arrival_ms=arrival,
                    prompt_tokens=prompt,
                    output_tokens=output,
                    estimated_output_tokens=16 if i < 9 else 24,
                )
            )
        (outdir / f"{pattern}.json").write_text(
            json.dumps(dict(seed=seed, pattern=pattern, requests=rows), indent=2) + "\n"
        )


def make_example_latencies(path):
    rows = []
    for phase in PHASES:
        for preset in PRESETS:
            for batch in (1, 2, 4, 8, 16):
                for context in (128, 512, 2048):
                    directions = (
                        (
                            [("large", "small")]
                            if preset == "small"
                            else [("small", "large")]
                        )
                        if phase == "transition_decode"
                        else [("", "")]
                    )
                    for src, dst in directions:
                        base = (
                            (7 if preset == "large" else 5)
                            * (1 + 0.27 * (batch - 1))
                            * (1 + context / 4096)
                        )
                        value = (
                            base * (2.5 + context / 256)
                            if phase == "prefill"
                            else (
                                base + (3 if preset == "small" else 4)
                                if phase == "transition_decode"
                                else base
                            )
                        )
                        for repeat, factor in ((1, 0.98), (2, 1.02)):
                            rows.append(
                                dict(
                                    run_id="EXAMPLE_ONLY",
                                    preset=preset,
                                    batch_size=batch,
                                    context_tokens=context,
                                    phase=phase,
                                    tokens_timed=1 if phase != "decode" else 32,
                                    latency_ms=round(
                                        value
                                        * factor
                                        * (1 if phase != "decode" else 32),
                                        4,
                                    ),
                                    repeat=repeat,
                                    gpu="EXAMPLE_GPU",
                                    dtype="bfloat16",
                                    from_preset=src,
                                    to_preset=dst,
                                    model_revision="EXAMPLE_ONLY",
                                )
                            )
    write_csv(
        path,
        rows,
        [
            "run_id",
            "preset",
            "batch_size",
            "context_tokens",
            "phase",
            "tokens_timed",
            "latency_ms",
            "repeat",
            "gpu",
            "dtype",
            "from_preset",
            "to_preset",
            "model_revision",
        ],
    )


def choose_request(queue_pressure, threshold):
    return "small" if queue_pressure >= threshold else "large"


def simulate(trace_path, latencies, policy, config):
    _, requests = load_trace(trace_path)
    pending = list(requests)
    active = []
    time = 0.0
    logs = []
    iteration = 0
    threshold = int(config.get("pressure_threshold", 4))
    dwell = int(config.get("minimum_dwell_tokens", 4))
    allowed = set(
        tuple(x)
        for x in config.get(
            "allowed_switches", [["large", "small"], ["small", "large"]]
        )
    )
    max_batch = int(config.get("max_batch_size", 8))
    while pending or active:
        if not active and pending and pending[0].arrival_ms > time:
            time = pending[0].arrival_ms
        arrived = []
        while pending and pending[0].arrival_ms <= time:
            arrived.append(pending.pop(0))
        # FIFO prefill; one request per operation. Prefill and decode share one GPU timeline.
        if arrived:
            active.extend(arrived)
        to_prefill = next((r for r in active if r.prefill_end is None), None)
        if to_prefill is not None:
            pressure = len(active) + len([r for r in pending if r.arrival_ms <= time])
            preset = (
                "large"
                if policy == "static_large"
                else (
                    "small"
                    if policy == "static_small"
                    else choose_request(pressure, threshold)
                )
            )
            cost, source = latencies.cost(
                "prefill", preset, 1, to_prefill.prompt_tokens
            )
            start = time
            time += cost
            to_prefill.prefill_end = time
            to_prefill.prefill_preset = preset
            to_prefill.current_preset = preset
            logs.append(
                dict(
                    iteration=iteration,
                    operation="prefill",
                    request_ids=to_prefill.request_id,
                    preset=preset,
                    from_preset="",
                    start_ms=start,
                    end_ms=time,
                    batch_size=1,
                    context_tokens=to_prefill.prompt_tokens,
                    cost_source=source,
                    reason="FIFO prefill; shared GPU",
                )
            )
            iteration += 1
            continue
        ready = [
            r
            for r in active
            if r.prefill_end is not None and r.tokens < r.output_tokens
        ]
        if not ready:
            active = [r for r in active if r.tokens < r.output_tokens]
            continue
        pressure = len(active) + sum(r.arrival_ms <= time for r in pending)
        desired = choose_request(pressure, threshold)
        choices = {}
        for r in ready:
            choice = r.current_preset
            reason = "fixed at request start"
            if policy == "iteration" and desired != choice:
                if (
                    r.tokens - r.last_switch_token >= dwell
                    and (choice, desired) in allowed
                ):
                    choice = desired
                    reason = f"pressure={pressure}; dwell satisfied"
                else:
                    reason = "switch blocked by dwell or allowed_switches"
            choices[r.request_id] = (choice, reason)
        # One common preset per GPU operation. Different request widths execute sequentially.
        groups = {}
        for r in ready:
            groups.setdefault(choices[r.request_id][0], []).append(r)
        for preset in PRESETS:
            group = groups.get(preset, [])
            for offset in range(0, len(group), max_batch):
                batch = group[offset : offset + max_batch]
                # Context buckets are processed separately: no free heterogeneous-context batch.
                by_context = {}
                for r in batch:
                    bucket = min(
                        (128, 512, 2048), key=lambda c: abs(c - r.context_tokens)
                    )
                    by_context.setdefault(bucket, []).append(r)
                for bucket, members in by_context.items():
                    switched = [r for r in members if r.current_preset != preset]
                    stable = [r for r in members if r.current_preset == preset]
                    # Transition and fixed-width groups cannot be billed as one free batch.
                    for subgroup, phase in (
                        (stable, "decode"),
                        (switched, "transition_decode"),
                    ):
                        if not subgroup:
                            continue
                        # Transition directions are homogeneous within a two-preset group.
                        context = bucket
                        src = (
                            subgroup[0].current_preset
                            if phase == "transition_decode"
                            else ""
                        )
                        cost, source = latencies.cost(
                            phase, preset, len(subgroup), context, src
                        )
                        start = time
                        time += cost
                        for r in subgroup:
                            if phase == "transition_decode":
                                r.switches += 1
                                r.last_switch_token = r.tokens
                                r.current_preset = preset
                            r.tokens += 1
                            r.token_times.append(time)
                            r.token_presets.append(preset)
                        logs.append(
                            dict(
                                iteration=iteration,
                                operation=phase,
                                request_ids="|".join(r.request_id for r in subgroup),
                                preset=preset,
                                from_preset=src,
                                start_ms=start,
                                end_ms=time,
                                batch_size=len(subgroup),
                                context_tokens=context,
                                cost_source=source,
                                reason=choices[subgroup[0].request_id][1],
                            )
                        )
                        iteration += 1
        active = [r for r in active if r.tokens < r.output_tokens]
    ttft_slo = config.get("ttft_slo_ms")
    itl_slo = config.get("itl_slo_ms")
    results = []
    for r in requests:
        ttft = r.token_times[0] - r.arrival_ms
        gaps = [b - a for a, b in zip(r.token_times, r.token_times[1:])]
        max_itl = max(gaps, default=0.0)
        passed = (ttft_slo is None or ttft <= ttft_slo) and (
            itl_slo is None or max_itl <= itl_slo
        )
        results.append(
            dict(
                policy=policy,
                request_id=r.request_id,
                arrival_ms=r.arrival_ms,
                prompt_tokens=r.prompt_tokens,
                output_tokens=r.output_tokens,
                estimated_output_tokens=r.estimated_output_tokens,
                prefill_preset=r.prefill_preset,
                decode_presets="|".join(r.token_presets),
                ttft_ms=round(ttft, 3),
                max_itl_ms=round(max_itl, 3),
                mean_itl_ms=round(statistics.mean(gaps), 3) if gaps else 0,
                completion_latency_ms=round(r.token_times[-1] - r.arrival_ms, 3),
                completion_ms=round(r.token_times[-1], 3),
                switch_count=r.switches,
                latency_slo_pass=passed,
            )
        )
    elapsed = max(r.token_times[-1] for r in requests) - min(
        r.arrival_ms for r in requests
    )
    summary = dict(
        policy=policy,
        requests=len(requests),
        makespan_ms=round(elapsed, 3),
        throughput_requests_per_s=round(len(requests) * 1000 / elapsed, 4),
        latency_only_simulated_goodput_requests_per_s=round(
            sum(x["latency_slo_pass"] for x in results) * 1000 / elapsed, 4
        ),
        mean_ttft_ms=round(statistics.mean(x["ttft_ms"] for x in results), 3),
        mean_completion_ms=round(
            statistics.mean(x["completion_latency_ms"] for x in results), 3
        ),
        switches=sum(x["switch_count"] for x in results),
        quality_constrained_goodput="NOT_EVALUATED",
    )
    return results, logs, summary


def plot_svg(path, summaries):
    width, height = 760, 350
    values = [s["latency_only_simulated_goodput_requests_per_s"] for s in summaries]
    vmax = max(values + [1]) * 1.15
    bars = []
    for i, s in enumerate(summaries):
        x = 60 + i * 170
        barh = 240 * values[i] / vmax
        bars.append(
            f'<rect x="{x}" y="{290-barh:.1f}" width="105" height="{barh:.1f}" fill="#286f9b"/><text x="{x}" y="315" font-size="11">{s["policy"]}</text><text x="{x}" y="{280-barh:.1f}" font-size="12">{values[i]:.2f}</text>'
        )
    Path(path).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/><text x="30" y="30" font-size="18">Burst trace: latency-only simulated goodput</text><text x="30" y="50" font-size="12">EXAMPLE_ONLY timings; requests/s; no quality eligibility</text><line x1="40" y1="290" x2="740" y2="290" stroke="black"/>{"".join(bars)}</svg>'
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="week1/scheduler/demo_out")
    p.add_argument("--latency-csv")
    p.add_argument("--quality-jsonl")
    p.add_argument(
        "--config", default=str(Path(__file__).with_name("config.example.json"))
    )
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    traces = out / "traces"
    make_traces(traces)
    latency_path = args.latency_csv or out / "example_latencies.csv"
    if not args.latency_csv:
        make_example_latencies(latency_path)
    lat = Latencies(latency_path, allow_nearest_example=True)
    config = json.loads(Path(args.config).read_text())
    if args.quality_jsonl:
        records = load_quality(args.quality_jsonl)
        (out / "quality_input_summary.json").write_text(
            json.dumps(
                dict(
                    records=len(records),
                    example_only=all(r["run_id"] == "EXAMPLE_ONLY" for r in records),
                    used_for_online_decisions=False,
                ),
                indent=2,
            )
            + "\n"
        )
    summaries = []
    for trace in sorted(traces.glob("*.json")):
        for policy in ("static_large", "static_small", "request", "iteration"):
            results, logs, summary = simulate(trace, lat, policy, config)
            stem = f"{trace.stem}_{policy}"
            write_csv(out / f"{stem}_requests.csv", results, list(results[0]))
            write_csv(out / f"{stem}_decisions.csv", logs, list(logs[0]))
            summaries.append(dict(trace=trace.stem, **summary))
    write_csv(out / "comparison.csv", summaries, list(summaries[0]))
    plot_svg(out / "burst_goodput.svg", [s for s in summaries if s["trace"] == "burst"])
    (out / "run_metadata.json").write_text(
        json.dumps(
            dict(
                latency_csv=str(latency_path),
                latency_source="EXAMPLE_ONLY" if lat.example else "MEASURED",
                aggregation="median of per-step raw repeat costs",
                nearest_example_fallback=lat.example,
                config=config,
                quality_eligibility="NOT_SUPPLIED",
            ),
            indent=2,
        )
        + "\n"
    )
    print(f"Wrote {out / 'comparison.csv'} and {out / 'burst_goodput.svg'}")


if __name__ == "__main__":
    main()

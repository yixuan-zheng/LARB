#!/usr/bin/env python3
"""Design-time multi-server rehearsal on the frozen P0 traces.

This is not a measured result. It checks that the provisional traces produce
the intended regimes (no queue in low; pressure in sustained/burst) and gives a
phase-duration estimate for the GPU schedule.
"""
import heapq
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from larb_scaled import config, workload  # noqa: E402

SERVERS = 32
THRESHOLD = 8


def lognormal(median, p90):
    sigma = math.log(p90 / median) / 1.2815515655446004
    mu = math.log(median)
    return lambda rng: rng.lognormvariate(mu, sigma)


def simulate(rows, seed=20261113):
    rng = random.Random(seed)
    signal_service = lognormal(150.0, 220.0)
    filler_service = lognormal(35.0, 55.0)
    arrivals = sorted(rows, key=lambda row: (row["arrival_s"], row["trace_id"]))
    service = {}
    for row in arrivals:
        service[row["trace_id"]] = (signal_service(rng) if row["class"] == "signal"
                                    else filler_service(rng))
    events = []
    for index, row in enumerate(arrivals):
        heapq.heappush(events, (row["arrival_s"], 0, index))
    running = []
    waiting = []
    waiting_count = 0
    free = SERVERS
    start_time = {}
    finish_time = {}
    pressure_time = 0.0
    total_time = 0.0
    current = 0.0
    max_waiting = 0
    last = 0.0
    while events:
        time, kind, index = heapq.heappop(events)
        if time > last:
            dt = time - last
            total_time += dt
            if waiting_count >= THRESHOLD:
                pressure_time += dt
            last = time
        current = time
        if kind == 0:
            waiting.append(index)
            waiting_count = len(waiting)
            max_waiting = max(max_waiting, waiting_count)
            while free > 0 and waiting:
                item = waiting.pop(0)
                waiting_count = len(waiting)
                free -= 1
                start_time[item] = time
                heapq.heappush(events, (time + service[arrivals[item]["trace_id"]], 1, item))
        else:
            finish_time[index] = time
            free += 1
            while free > 0 and waiting:
                item = waiting.pop(0)
                waiting_count = len(waiting)
                free -= 1
                start_time[item] = time
                heapq.heappush(events, (time + service[arrivals[item]["trace_id"]], 1, item))
    latencies = []
    misses = 0
    waits = []
    signal_misses = signal_n = filler_misses = filler_n = 0
    for index, row in enumerate(arrivals):
        finish = finish_time.get(index)
        if finish is None:
            continue
        latency = finish - row["arrival_s"]
        latencies.append(latency)
        waits.append(start_time[index] - row["arrival_s"])
        missed = latency > row["deadline_s"]
        if missed:
            misses += 1
        if row["class"] == "signal":
            signal_n += 1
            signal_misses += 1 if missed else 0
        else:
            filler_n += 1
            filler_misses += 1 if missed else 0
    latencies.sort()
    waits.sort()

    def q(values, p):
        return values[min(len(values) - 1, int(p * (len(values) - 1)))] if values else None

    total_service = sum(service.values())
    wall = max(finish_time.values()) if finish_time else 0.0
    return {
        "requests": len(arrivals),
        "signal": sum(row["class"] == "signal" for row in arrivals),
        "filler": sum(row["class"] == "filler" for row in arrivals),
        "servers": SERVERS,
        "wall_s": wall,
        "utilization": total_service / (SERVERS * wall) if wall else None,
        "pressure_threshold": THRESHOLD,
        "pressure_fraction": pressure_time / total_time if total_time else None,
        "max_waiting": max_waiting,
        "mean_wait_s": sum(waits) / len(waits) if waits else None,
        "p50_wait_s": q(waits, 0.5),
        "p90_wait_s": q(waits, 0.9),
        "p50_latency_s": q(latencies, 0.5),
        "p90_latency_s": q(latencies, 0.9),
        "p99_latency_s": q(latencies, 0.99),
        "deadline_misses": misses,
        "miss_rate": misses / len(latencies) if latencies else None,
        "signal_miss_rate": signal_misses / signal_n if signal_n else None,
        "filler_miss_rate": filler_misses / filler_n if filler_n else None,
        "mean_service_s": total_service / len(service) if service else None,
    }


def main():
    config.RESULTS_DIR.joinpath("p0").mkdir(parents=True, exist_ok=True)
    output = {"generated_at": config.utc_now(), "note": "Design-time FIFO rehearsal; not measured.",
              "conditions": {}}
    for condition in workload.CONDITIONS:
        path = config.ARTIFACTS_DIR / "traces" / f"{condition}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        output["conditions"][condition] = simulate(rows)
    config.write_json(config.RESULTS_DIR / "p0/synthetic.json", output)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

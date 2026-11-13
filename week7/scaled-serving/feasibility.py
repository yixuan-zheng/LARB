#!/usr/bin/env python3
"""CPU-only feasibility checks for week7/scaled-serving.

No GPU, no vLLM, no model. Reproduces the planning tables in
plan/12-feasibility-notes.md from saved records and simple arithmetic.

Run:
    python3 week7/scaled-serving/feasibility.py
    python3 week7/scaled-serving/feasibility.py --quick

The default 12,000-arrival-per-cell queue run is the one reported in
plan/12-feasibility-notes.md; --quick is a fast sanity check with different Monte
Carlo noise.
"""
import argparse
import heapq
import json
import math
import random
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
METRICS = REPO / "week6/admission-timing-audit/evidence/response-metrics.json"

Z975 = 1.959963984540054
Z80 = 0.8416212335729143


def md_table(headers, rows):
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        print("| " + " | ".join(str(x) for x in row) + " |")
    print()


def kv_table():
    layers, kv_heads, head_dim, nbytes = 36, 8, 128, 2
    per_token = 2 * layers * kv_heads * head_dim * nbytes
    print("## KV cache and concurrency\n")
    print(f"KV bytes/token: {per_token} = {per_token / 1024:.1f} KiB/token\n")
    rows = []
    for util in (0.80, 0.85, 0.90):
        for ctx in (8192, 12288, 16384, 20480, 24576):
            budget = 80 * util - 8.2
            per_req = ctx * per_token / 1e9
            rows.append((f"{util:.2f}", ctx, f"{per_req:.2f}", int(budget / per_req)))
    md_table(["GPU util", "Context", "KV/request (GB)", "Max sequences"], rows)
    print(f"32 x 8.3k tokens: {32 * 8300 * per_token / 1e9:.1f} GB of KV")
    print(f"32 x 16.3k tokens: {32 * 16300 * per_token / 1e9:.1f} GB of KV\n")


def power_table():
    print("## Paired binary power\n")
    rows = []
    for effect in (0.03, 0.04, 0.05, 0.06, 0.08, 0.10):
        row = [f"{effect:.02f}"]
        for disc in (0.10, 0.15, 0.20, 0.25, 0.30):
            n = (Z975 + Z80) ** 2 * disc / effect ** 2
            row.append(str(math.ceil(n)))
        rows.append(row)
    md_table(["Effect", "disc .10", "disc .15", "disc .20", "disc .25", "disc .30"], rows)

    rows = []
    for n in (200, 300, 500, 800, 1200, 2000, 3200):
        row = [n]
        for disc in (0.10, 0.15, 0.20, 0.25, 0.30):
            mde = math.sqrt((Z975 + Z80) ** 2 * disc / n) * 100
            row.append(f"{mde:.1f}")
        rows.append(row)
    print("80%-power MDE in percentage points:\n")
    md_table(["n", "disc .10", "disc .15", "disc .20", "disc .25", "disc .30"], rows)


def effective_n_table():
    print("## Effective paired units with question clustering\n")
    print("n_eff = Q * m / (1 + (m - 1) * ICC)\n")
    rows = []
    for q in (200, 220, 246, 500, 800):
        for m in (4, 6):
            row = [q, m]
            for icc in (0.2, 0.4, 0.6):
                n_eff = q * m / (1 + (m - 1) * icc)
                row.append(f"{n_eff:.0f}")
            # 80% MDE at 20% discordance for the ICC .2 and .4 endpoints
            for icc in (0.2, 0.4):
                n_eff = q * m / (1 + (m - 1) * icc)
                row.append(f"{100 * math.sqrt((Z975 + Z80) ** 2 * 0.20 / n_eff):.1f}")
            rows.append(row)
    md_table(["Questions", "Seeds", "n_eff .2", "n_eff .4", "n_eff .6",
              "MDE .2", "MDE .4"], rows)


def _lognormal(median, p90):
    sigma = math.log(p90 / median) / 1.2815515655446004
    mu = math.log(median)
    return lambda rng: rng.lognormvariate(mu, sigma)


def _mixture(parts):
    total = sum(w for w, _ in parts)
    cumulative, acc = [], 0.0
    for weight, sampler in parts:
        acc += weight / total
        cumulative.append((acc, sampler))

    def draw(rng):
        u = rng.random()
        for cut, sampler in cumulative:
            if u <= cut:
                return sampler(rng)
        return cumulative[-1][1](rng)

    return draw


def _simulate(lam, servers, service, deadline, n, seed=17):
    rng = random.Random(seed)
    heap = [0.0] * servers
    heapq.heapify(heap)
    latencies = []
    misses = 0
    t = 0.0
    for _ in range(n):
        t += rng.expovariate(lam)
        start = max(t, heapq.heappop(heap))
        finish = start + service(rng)
        heapq.heappush(heap, finish)
        latency = finish - t
        latencies.append(latency)
        if latency > deadline:
            misses += 1
    latencies.sort()

    def q(p):
        return latencies[min(len(latencies) - 1, int(p * (len(latencies) - 1)))]

    return misses / n, statistics.mean(latencies), q(0.5), q(0.9)


def queue_table(quick=False):
    print("## Queue simulation: mixed workload, 32 servers\n")
    service = _mixture([(0.55, _lognormal(150, 220)), (0.45, _lognormal(35, 55))])
    n = 4000 if quick else 12000
    mean_rng = random.Random(123)
    mean = sum(service(mean_rng) for _ in range(20000)) / 20000
    print(f"Mean service time: {mean:.1f} s; n per cell: {n}\n")
    rows = []
    for util in (0.70, 0.80, 0.90, 0.95, 1.00, 1.05):
        lam = util * 32 / mean
        cells = []
        for deadline in (180, 210, 240):
            miss, _, _, _ = _simulate(lam, 32, service, deadline, n)
            cells.append(f"{miss:.2f}")
        _, _, med, p90 = _simulate(lam, 32, service, 180, n)
        rows.append((f"{util:.2f}", f"{lam * 3600:.0f}", *cells, f"{med:.0f}", f"{p90:.0f}"))
    md_table(["Util", "Arrivals/h", "Miss@180", "Miss@210", "Miss@240",
              "Median latency", "p90 latency"], rows)


def roofline_table():
    print("## Throughput roofline (H100, 2.8 TB/s effective)\n")
    per_token = 147456
    weights = 8.2
    rows = []
    for batch in (2, 8, 16, 32, 48):
        for ctx in (6000, 8300):
            kv = batch * ctx * per_token / 1e9
            step_ms = (weights + kv) / 2800 * 1000
            aggregate = batch / (step_ms / 1000)
            rows.append((batch, ctx, f"{kv:.1f}", f"{step_ms:.1f}", f"{aggregate:.0f}"))
    md_table(["Batch", "Context", "KV (GB)", "Step (ms)", "Aggregate tok/s"], rows)


def _quantile(values, p):
    values = sorted(values)
    if not values:
        return None
    return values[min(len(values) - 1, int(p * (len(values) - 1)))]


def answer_stats():
    print("## Saved answer-phase statistics\n")
    if not METRICS.exists():
        print(f"Missing {METRICS}; skipping.\n")
        return
    records = [r for r in json.loads(METRICS.read_text()) if r.get("role") == "measured"]
    rows = []
    for label, group in (
        ("all", records),
        ("correct", [r for r in records if r.get("correct")]),
        ("incorrect", [r for r in records if not r.get("correct")]),
    ):
        values = [r["answer_tokens_after_close"] for r in group
                  if r.get("answer_tokens_after_close") is not None]
        if not values:
            continue
        rows.append((label, len(values), _quantile(values, 0.1), _quantile(values, 0.5),
                     _quantile(values, 0.9), max(values)))
    md_table(["Group", "n", "p10", "median", "p90", "max"], rows)

    caps = [r for r in records if r.get("reason") == "answer_cap"]
    print(f"Answer-cap failures: {len(caps)}/{len(records)} = "
          f"{100 * len(caps) / len(records):.1f}%\n")

    lookup = {(r["run"], r["policy"], r["id"], r["seed"]): r for r in records}
    rows = []
    for run in sorted({r["run"] for r in records}):
        for a, b in (("fixed4k", "fixed8k"), ("fixed4k", "live"),
                     ("fixed8k", "live"), ("arrival", "live")):
            pairs = [(r, lookup[(run, b, r["id"], r["seed"])]) for r in records
                     if r["run"] == run and r["policy"] == a
                     and (run, b, r["id"], r["seed"]) in lookup]
            if not pairs:
                continue
            both = sum(1 for x, y in pairs if x["good"] and y["good"])
            neither = sum(1 for x, y in pairs if not x["good"] and not y["good"])
            a_only = sum(1 for x, y in pairs if x["good"] and not y["good"])
            b_only = sum(1 for x, y in pairs if not x["good"] and y["good"])
            discordance = (a_only + b_only) / len(pairs)
            rows.append((run, f"{a} vs {b}", len(pairs), both, neither, a_only, b_only,
                         f"{discordance:.2f}"))
    print("Paired correct-on-time categories:\n")
    md_table(["Run", "Pair", "n", "both", "neither", "a only", "b only", "discordance"], rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="shorter queue simulation")
    args = parser.parse_args()
    kv_table()
    power_table()
    effective_n_table()
    queue_table(quick=args.quick)
    roofline_table()
    answer_stats()


if __name__ == "__main__":
    main()


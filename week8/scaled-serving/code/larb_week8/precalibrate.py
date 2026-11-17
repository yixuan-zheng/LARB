"""CPU pre-calibration for the 240 s SLO.

The P1 180 s points place the knee between 800/h (0% misses) and 931/h
(74.7%).  A load-independent queue simulation cannot reproduce that jump
because service time grows with batch size; the simulation is therefore used
only to show the shape and the lower bound, while the GPU grid is chosen to
bracket the observed knee finely.
"""
from __future__ import annotations

import heapq
import json
import random
import statistics
from pathlib import Path

from larb_week8 import config

P1 = config.WEEK7_ROOT / "results/p1"
REQUEST_DIRS = [
    P1 / "calibration-lower/rates/requests",
    P1 / "calibration-mid/rates/requests",
    P1 / "calibration/rates/requests",
]


def load_service_times() -> tuple[list[float], list[float]]:
    signal, filler = [], []
    for folder in REQUEST_DIRS:
        for path in folder.glob("*.json"):
            raw = json.loads(path.read_text())
            if raw.get("finished") is None or raw.get("scheduler_start") is None:
                continue
            value = raw["finished"] - raw["scheduler_start"]
            (signal if raw["class"] == "signal" else filler).append(value)
    if not signal or not filler:
        raise FileNotFoundError("no P1 service-time records found")
    return signal, filler


def observed_points() -> list[dict]:
    points = []
    for rate, folder in ((500, "calibration-lower"), (650, "calibration-lower"),
                         (800, "calibration-mid"), (931, "calibration"),
                         (1164, "calibration"), (1397, "calibration")):
        path = P1 / folder / "calibration.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for row in data.get("rates", []):
            if str(rate) in row.get("condition", ""):
                points.append({"rate_per_hour": rate,
                               "miss_rate": row["signal_miss_rate"],
                               "signal": row.get("signal"),
                               "p50_latency": row.get("signal_latency_p50"),
                               "p90_latency": row.get("signal_latency_p90")})
    return sorted(points, key=lambda item: item["rate_per_hour"])


def simulate(rate: float, deadline: float, signal: list[float], filler: list[float],
             load_factor: float = 0.0, servers: int = 32, filler_share: float = 0.3,
             minutes: float = 25.0, warmup_minutes: float = 10.0, seed: int = 1) -> dict:
    rng = random.Random(seed)
    total = max(2, int(round(rate * minutes / 60.0)))
    rows = []
    t = 0.0
    for _ in range(total):
        t += rng.expovariate(rate / 3600.0)
        is_signal = rng.random() < (1.0 - filler_share)
        rows.append((t, is_signal, rng.choice(signal if is_signal else filler)))
    finishes = [0.0] * servers
    warmup_s = warmup_minutes * 60.0
    misses = measured = 0
    latencies = []
    for arrival, is_signal, duration in rows:
        idx = min(range(servers), key=lambda i: finishes[i])
        start = max(arrival, finishes[idx])
        busy = sum(1 for finish in finishes if finish > arrival)
        multiplier = 1.0 + load_factor * max(0, busy - 20) / 12.0
        finish = start + duration * multiplier
        finishes[idx] = finish
        if is_signal and arrival >= warmup_s:
            measured += 1
            latency = finish - arrival
            latencies.append(latency)
            if latency > deadline:
                misses += 1
    latencies.sort()

    def q(p):
        return latencies[min(len(latencies) - 1, int(p * (len(latencies) - 1)))] if latencies else None

    return {"rate_per_hour": rate, "measured_signal": measured,
            "miss_rate": (misses / measured) if measured else None,
            "p50_latency": q(0.50), "p90_latency": q(0.90)}


def curve(deadline: float, load_factor: float, signal: list[float],
          filler: list[float], rates=None, seeds=5) -> list[dict]:
    rates = rates or list(range(500, 1251, 50))
    out = []
    for rate in rates:
        runs = [simulate(rate, deadline, signal, filler, load_factor=load_factor, seed=seed)
                for seed in range(seeds)]
        out.append({"rate_per_hour": rate,
                    "miss_rate_mean": statistics.mean(r["miss_rate"] for r in runs),
                    "miss_rate_min": min(r["miss_rate"] for r in runs),
                    "miss_rate_max": max(r["miss_rate"] for r in runs)})
    return out


def recommend_grid(predicted: list[dict], observed: list[dict]) -> dict:
    band = [0.15, 0.40]
    in_band = [row["rate_per_hour"] for row in predicted
               if band[0] <= row["miss_rate_mean"] <= band[1]]
    # The empirical 180 s knee is the strongest evidence; the grid starts
    # below it and extends above the predicted 240 s band.
    grid = [600, 650, 700, 750, 800, 850, 900, 950, 1000, 1050, 1100, 1150, 1200]
    if in_band:
        low = max(500, min(in_band) - 100)
        high = min(1400, max(in_band) + 100)
        grid = sorted(set(grid + list(range(low, high + 1, 50))))
    return {
        "band": band,
        "predicted_rates_in_band": in_band,
        "observed_180s_knee": {"below": [p for p in observed if p["miss_rate"] < band[0]],
                               "above": [p for p in observed if p["miss_rate"] > band[1]]},
        "recommended_rates_per_hour": grid,
        "minutes_per_rate": 25,
        "rationale": "Bracket the empirical 180 s knee and the predicted 240 s band; 25 min per rate includes a 10 min warm-up.",
    }


def run() -> dict:
    signal, filler = load_service_times()
    observed = observed_points()
    predicted = curve(240.0, 0.0, signal, filler)
    predicted_load = curve(240.0, 0.2, signal, filler)
    recommended = recommend_grid(predicted, observed)
    return {
        "generated_at": config.utc_now(),
        "service_time_source": [str(path) for path in REQUEST_DIRS],
        "service_time_summary": {
            "signal_n": len(signal),
            "signal_p50": statistics.median(signal),
            "signal_p90": sorted(signal)[int(0.9 * (len(signal) - 1))],
            "filler_n": len(filler),
            "filler_p50": statistics.median(filler),
            "filler_p90": sorted(filler)[int(0.9 * (len(filler) - 1))],
        },
        "observed_180s": observed,
        "predicted_240s_load_independent": predicted,
        "predicted_240s_load_factor_0_2": predicted_load,
        "recommendation": recommended,
        "caveat": ("The load-independent simulation predicts a much lower miss rate at 931/h than the "
                   "observed 74.7%; the engine's service time grows with batch size and the queue "
                   "dominates the knee. Use the empirical P1 bracket for the GPU grid, not the "
                   "simulation as a point predictor."),
    }


def write_markdown(result: dict, path: Path) -> None:
    lines = ["# CPU pre-calibration for the 240 s SLO", "",
             f"Generated: {result['generated_at']}", "",
             "## Observed P1 points (180 s)", "",
             "| rate/h | signal | miss rate | p50 latency | p90 latency |",
             "|---:|---:|---:|---:|---:|"]
    for row in result["observed_180s"]:
        lines.append(f"| {row['rate_per_hour']} | {row['signal']} | {row['miss_rate']:.3f} | "
                     f"{row['p50_latency']:.0f} | {row['p90_latency']:.0f} |")
    lines.append("")
    lines.append("## Predicted 240 s curve (load-independent, 5 seeds)")
    lines.append("")
    lines.append("| rate/h | mean miss | min | max |")
    lines.append("|---:|---:|---:|---:|")
    for row in result["predicted_240s_load_independent"]:
        lines.append(f"| {row['rate_per_hour']} | {row['miss_rate_mean']:.3f} | "
                     f"{row['miss_rate_min']:.3f} | {row['miss_rate_max']:.3f} |")
    lines.append("")
    lines.append("## Recommended GPU grid")
    lines.append("")
    lines.append(f"`{result['recommendation']['recommended_rates_per_hour']}` per hour, "
                 f"{result['recommendation']['minutes_per_rate']} minutes each")
    lines.append("")
    lines.append(result["caveat"])
    lines.append("")
    Path(path).write_text("\n".join(lines) + "\n")


def main() -> dict:
    result = run()
    out = config.RESULTS_DIR / "precalibration-240.json"
    report = config.REPORTS_DIR / "PRECALIBRATION-240.md"
    config.write_json(out, result)
    write_markdown(result, report)
    print(json.dumps({"out": str(out), "report": str(report),
                      "recommended": result["recommendation"]["recommended_rates_per_hour"],
                      "observed": result["observed_180s"]}, indent=2))
    return result


if __name__ == "__main__":
    main()


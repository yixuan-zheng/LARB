#!/usr/bin/env python3
"""CPU-only plans for the two P1 gates that are not phase-trace plans:
throughput sweep and load/deadline calibration.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from larb_scaled import config  # noqa: E402


def main():
    p1 = config.load_p1_gates()
    throughput = p1["gates"]["throughput"]
    calibration = p1["gates"]["calibration"]
    points = len(throughput["concurrency"]) * len(throughput["thinking_tokens"])
    plan = {
        "generated_at": config.utc_now(),
        "throughput": {
            **throughput,
            "points": points,
            "estimated_minutes": points * throughput["seconds_per_point"] / 60,
            "note": "Add one 8,192-thinking point at the chosen concurrency for the N estimate.",
        },
        "calibration": {
            **calibration,
            "signal_questions": 48,
            "seeds": 4,
            "filler_share": 0.30,
            "expected_requests": 274,
            "note": "Run fixed8k at each rate; choose 15-40% signal misses, then freeze the main trace.",
        },
    }
    config.write_json(ROOT / "results/p0/p1-sweeps-plan.json", plan)
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()

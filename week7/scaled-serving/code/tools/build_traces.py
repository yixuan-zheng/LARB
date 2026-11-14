#!/usr/bin/env python3
"""Build the provisional P0 traces and the P1 gate traces.

The main traces are provisional until P1 Gate F calibrates the arrival rate.
Gate traces are small, arm-agnostic traces used by the P1 gate runner.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from larb_scaled import config, workload  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrated-rate", type=float, default=None,
                    help="Gate F sustained arrivals per hour; also used as the burst baseline")
    ap.add_argument("--seeds", type=int, default=None,
                    help="Gate C seed count for sustained/burst (default: protocol)")
    args = ap.parse_args()
    protocol = config.load_protocol()
    cohort = config.load_cohort()
    questions = workload.load_questions()
    if args.calibrated_rate:
        protocol["workload"]["conditions"]["sustained"]["provisional_rate_per_hour"] = args.calibrated_rate
        protocol["workload"]["conditions"]["burst"]["provisional_baseline_per_hour"] = args.calibrated_rate
        protocol["workload"]["conditions"]["burst"]["recovery_rate_per_hour"] = args.calibrated_rate
    config.ARTIFACTS_DIR.joinpath("traces").mkdir(parents=True, exist_ok=True)
    manifest = {"generated_at": config.utc_now(), "provisional": not bool(args.calibrated_rate),
                "calibrated_rate_per_hour": args.calibrated_rate,
                "protocol_sha256": config.digest(config.CONFIG_DIR / "protocol.json"),
                "cohort_sha256": config.digest(config.ARTIFACTS_DIR / "cohort.json"),
                "traces": {}}
    for condition in workload.CONDITIONS:
        seeds = args.seeds if (args.seeds and condition in ("sustained", "burst")) else None
        rows = workload.build_trace(condition, cohort, questions, protocol, seeds=seeds)
        path = config.ARTIFACTS_DIR / "traces" / f"{condition}.jsonl"
        sha = workload.write_trace(path, rows)
        manifest["traces"][condition] = {
            "file": str(path.relative_to(ROOT)),
            "sha256": sha,
            "summary": workload.trace_summary(rows),
            "provisional": not bool(args.calibrated_rate),
            "arrival_rate_per_hour": (args.calibrated_rate if condition in ("sustained", "burst")
                                      and args.calibrated_rate else None),
            "seeds_override": seeds,
            "note": ("Calibrated by P1 Gate F." if args.calibrated_rate
                     else "Provisional P0 arrival rate; replace after P1 Gate F calibration."),
        }
    gates = {
        # Quality gates: the deadline is loose and scoring is per response, so
        # arrivals are denser than the main traces to fit the gate allocation.
        "gate-bridge": ("bridge_ids", 2, 2.0, 1800.0, None),
        "gate-screen": ("screen_ids", 1, 1.5, 1800.0, None),
        "gate-preview": ("preview_ids", 1, 1.5, 1800.0, None),
        "gate-contract": ("screen_ids", 2, 1.5, 1800.0, None),
        "gate-mechanics": ("screen_ids", 1, 0.5, 1800.0, 32),
    }
    for name, (ids_key, seeds, spacing, deadline, limit) in gates.items():
        rows = workload.build_gate_trace(name, ids_key, seeds, cohort, questions,
                                         protocol, spacing_s=spacing,
                                         deadline_s=deadline, limit=limit)
        path = config.ARTIFACTS_DIR / "traces" / f"{name}.jsonl"
        sha = workload.write_trace(path, rows)
        manifest["traces"][name] = {
            "file": str(path.relative_to(ROOT)),
            "sha256": sha,
            "summary": workload.trace_summary(rows),
            "provisional": False,
            "note": "P1 gate trace; deadline is loose because these gates score quality, not SLO attainment.",
        }
    # Second mechanics order: same 32 rows, reversed admission order.
    base = workload.build_gate_trace("gate-mechanics-r2", "screen_ids", 1, cohort, questions,
                                     protocol, spacing_s=0.5, deadline_s=1800.0, limit=32)
    reversed_rows = []
    for index, row in enumerate(reversed(base)):
        row = dict(row)
        row["arrival_s"] = round(index * 0.5, 6)
        reversed_rows.append(row)
    reversed_rows.sort(key=lambda row: (row["arrival_s"], row["trace_id"]))
    workload.validate_trace(reversed_rows, "gate-mechanics-r2", protocol, cohort, questions,
                           allowed_signal_ids=cohort["screen_ids"][:32])
    path = config.ARTIFACTS_DIR / "traces" / "gate-mechanics-r2.jsonl"
    sha = workload.write_trace(path, reversed_rows)
    manifest["traces"]["gate-mechanics-r2"] = {
        "file": str(path.relative_to(ROOT)), "sha256": sha,
        "summary": workload.trace_summary(reversed_rows), "provisional": False,
        "note": "Same 32 rows as gate-mechanics in reversed admission order (Gate A second run).",
    }
    config.write_json(config.ARTIFACTS_DIR / "traces/manifest.json", manifest)
    print(json.dumps({name: item["summary"] for name, item in manifest["traces"].items()}, indent=2))


if __name__ == "__main__":
    main()

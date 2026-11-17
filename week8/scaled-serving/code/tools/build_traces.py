#!/usr/bin/env python3
"""Build the Week 8 qualification traces (CPU-only).

Examples:
    PYTHONPATH=week8/scaled-serving/code:week7/scaled-serving/code \
      python3 week8/scaled-serving/code/tools/build_traces.py --stage all
    ... --stage main --signal-rate 950 --cohort-variant main_after_preview48
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import larb_week8  # noqa: E402,F401
from larb_week8 import config, traces  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["preview", "calibration", "main", "all"],
                        default="all")
    parser.add_argument("--rates", type=float, nargs="+",
                        help="calibration rates per hour (default: qualify.json)")
    parser.add_argument("--minutes", type=float,
                        help="minutes per calibration point (default: qualify.json)")
    parser.add_argument("--signal-rate", type=float,
                        help="main sustained/burst arrival rate per hour")
    parser.add_argument("--cohort-variant", choices=["main", "main_after_preview48"],
                        default="main")
    parser.add_argument("--seeds", type=int, default=4)
    args = parser.parse_args()
    qualify = config.load_qualify()
    entries = {}
    if args.stage in ("preview", "all"):
        entries["gate-omni-preview"] = traces.build_preview(24)
        entries["gate-omni-preview48"] = traces.build_preview(48)
    if args.stage in ("calibration", "all"):
        rates = args.rates or qualify["calibration"]["candidate_rates_per_hour"]
        minutes = args.minutes or (qualify["calibration"]["total_seconds_per_rate"] / 60.0)
        for rate in rates:
            entry = traces.build_calibration(rate, minutes)
            entries[entry["condition"]] = entry
    if args.stage == "main" or (args.stage == "all" and args.signal_rate is not None):
        if not args.signal_rate:
            raise SystemExit("--signal-rate is required for a main trace")
        entries.update(traces.build_main(args.signal_rate, cohort_variant=args.cohort_variant,
                                         seeds=args.seeds))
    manifest = traces.write_manifest(entries)
    print(json.dumps({name: entry["summary"] for name, entry in entries.items()}, indent=2))
    print(json.dumps({"traces_in_manifest": len(manifest["traces"])}, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build the provisional P0 traces and the P1 gate traces.

The main traces are provisional until P1 Gate F calibrates the arrival rate.
Gate traces are small, arm-agnostic traces used by the P1 gate runner.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from larb_scaled import config, workload  # noqa: E402


def main():
    protocol = config.load_protocol()
    cohort = config.load_cohort()
    questions = workload.load_questions()
    config.ARTIFACTS_DIR.joinpath("traces").mkdir(parents=True, exist_ok=True)
    manifest = {"generated_at": config.utc_now(), "provisional": True,
                "protocol_sha256": config.digest(config.CONFIG_DIR / "protocol.json"),
                "cohort_sha256": config.digest(config.ARTIFACTS_DIR / "cohort.json"),
                "traces": {}}
    for condition in workload.CONDITIONS:
        rows = workload.build_trace(condition, cohort, questions, protocol)
        path = config.ARTIFACTS_DIR / "traces" / f"{condition}.jsonl"
        sha = workload.write_trace(path, rows)
        manifest["traces"][condition] = {
            "file": str(path.relative_to(ROOT)),
            "sha256": sha,
            "summary": workload.trace_summary(rows),
            "provisional": True,
            "note": "Provisional P0 arrival rate; replace after P1 Gate F calibration.",
        }
    gates = {
        "gate-bridge": ("bridge_ids", 2, 8.0, 1800.0, None),
        "gate-screen": ("screen_ids", 1, 8.0, 1800.0, None),
        "gate-preview": ("preview_ids", 1, 8.0, 1800.0, None),
        "gate-contract": ("screen_ids", 2, 8.0, 1800.0, None),
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
    config.write_json(config.ARTIFACTS_DIR / "traces/manifest.json", manifest)
    print(json.dumps({name: item["summary"] for name, item in manifest["traces"].items()}, indent=2))


if __name__ == "__main__":
    main()

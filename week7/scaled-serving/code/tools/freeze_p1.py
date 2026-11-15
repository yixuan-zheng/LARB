#!/usr/bin/env python3
"""Freeze the P1 decisions, the calibrated main traces and the source lock.

Run after Gate F has chosen the arrival rate and after
build_traces.py --calibrated-rate has rebuilt the main traces.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from larb_scaled import config  # noqa: E402


def gpu_metadata():
    try:
        text = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,uuid,memory.total,driver_version",
             "--format=csv,noheader"], capture_output=True, text=True,
            timeout=10).stdout.strip()
        return text.splitlines()[0] if text else None
    except Exception:
        return None


def gate_flag(block):
    if not isinstance(block, dict):
        return None
    if "pass_" in block:
        return block["pass_"]
    if "pass" in block:
        return block["pass"]
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gates", type=Path, default=ROOT / "results/p1/gates.json")
    parser.add_argument("--rate", type=float)
    parser.add_argument("--threshold", type=int, default=8)
    parser.add_argument("--withhold", action="store_true",
                        help="record that Gate E failed and P2 is not authorised")
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--seeds", type=int)
    parser.add_argument("--contract", default=None)
    parser.add_argument("--graphs", action="store_true")
    parser.add_argument("--no-graphs", action="store_true")
    args = parser.parse_args()
    gates = json.loads(args.gates.read_text()) if args.gates.exists() else {"gates": {}}
    recommendation = (gates.get("gates", {}).get("throughput", {}) or {}).get(
        "recommendation") or {}
    contract_block = gates.get("gates", {}).get("contract", {}) or {}
    concurrency = args.concurrency or recommendation.get("concurrency") or 32
    seeds = args.seeds or recommendation.get("seeds") or 4
    contract = args.contract or contract_block.get("selected") or "legacy"
    graphs = bool(args.graphs) and not args.no_graphs
    protocol = config.load_protocol()
    cohort = config.load_cohort()
    realised_questions = cohort["counts"]["main"]
    p2 = config.load_p2_main()
    p2.update(
        signal_questions=realised_questions,
        seeds=seeds,
        max_num_seqs=concurrency,
        answer_contract=contract,
        enforce_eager=not graphs,
        arrival_rate_per_hour=args.rate,
        pressure_threshold=args.threshold,
        pressure_persistence_steps=protocol["policy"]["pressure"]["persistence_steps"],
        source_lock="artifacts/source-lock-p1.json",
        p2_status=("withheld" if args.withhold else "ready"),
        notes=(("P2 withheld by Gate E: the main-cohort slope preview failed, so the pool "
                "must change before a main run. The rig decisions below are still frozen.")
               if args.withhold else
               ("Frozen by P1 Gate F: calibrated arrival rate, gate-selected "
                "concurrency/seeds/contract/graph mode. The sustained and burst "
                "traces were rebuilt at this rate.")),
    )
    config.write_json(config.CONFIG_DIR / "p2_main.json", p2)
    decisions = dict(
        max_num_seqs=concurrency, seeds=seeds, answer_contract=contract,
        cuda_graphs=graphs, arrival_rate_per_hour=args.rate,
        pressure_threshold=args.threshold,
        pressure_persistence_steps=protocol["policy"]["pressure"]["persistence_steps"],
        cut_target=protocol["policy"]["cut"]["target"],
        cut_progress_floor=protocol["policy"]["cut"]["progress_floor"],
        cut_min_saving=protocol["policy"]["cut"]["min_saving"],
        deadline_seconds=protocol["deadline"]["slo_seconds"],
        cohort_signal_questions=realised_questions,
        queued_engine_core=False,
        p2_authorised=not args.withhold,
        main_traces_rebuilt=bool(args.rate and not args.withhold),
    )
    freeze = dict(
        created_at=config.utc_now(), stage="P1", supersedes="P0 CPU freeze",
        p2_authorised=not args.withhold,
        p2_status=("withheld_gate_e_slope_preview_failed" if args.withhold else "ready"),
        decisions=decisions,
        gate_status={name: gate_flag(block)
                     for name, block in gates.get("gates", {}).items()},
        throughput_recommendation=recommendation,
        calibration_rate_per_hour=args.rate,
        trace_manifest="artifacts/traces/manifest.json",
        main_traces_rebuilt=bool(args.rate and not args.withhold),
    )
    config.write_json(config.CONFIG_DIR / "p1_freeze.json", freeze)
    lock = dict(
        created_at=config.utc_now(), stage="P1", job=os.environ.get("SLURM_JOB_ID"),
        gpu=gpu_metadata(), model=protocol["model"], engine=protocol["engine"],
        decisions=decisions, configs=config.config_hashes(),
        code=config.code_hashes(), artifacts=config.artifact_hashes(),
        freeze_sha256=config.digest(config.CONFIG_DIR / "p1_freeze.json"),
    )
    config.write_json(ROOT / "results/p1/source-lock.json", lock)
    # A tracked copy: results/ is gitignored by the project convention.
    config.write_json(config.ARTIFACTS_DIR / "source-lock-p1.json", lock)
    config.freeze_manifest(extra=dict(stage="P1", decisions=decisions,
                                      p2_authorised=not args.withhold,
                                      source_lock="artifacts/source-lock-p1.json"))
    print(json.dumps(dict(decisions=decisions, gate_status=freeze["gate_status"]), indent=2))


if __name__ == "__main__":
    main()

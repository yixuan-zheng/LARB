"""Decision record and frozen P2 packet writer."""
from __future__ import annotations

import json
import math
from pathlib import Path

from larb_week8 import config, traces


def select_seeds(rate: float, cohort_variant: str) -> tuple[int | None, dict]:
    """Largest pre-declared seed count that fits the 15 h inner allocation."""
    rule = config.load_qualify()["p2"]["seed_reduction_rule"]
    counts = config.load_cohort()["counts"]
    questions = (counts["main_after_preview48"]
                 if cohort_variant == "main_after_preview48" else counts["main"])
    low_hours = (rule["low_control_requests_per_arm"] * 4
                 / rule["low_rate_per_hour"])
    estimates = {}
    for seeds in rule["allowed_seeds"]:
        signal = questions * seeds
        filler = math.ceil(signal * 0.30 / 0.70)
        per_phase = signal + filler
        pressure_hours = rule["pressure_phases"] * per_phase / rate
        total = (pressure_hours + low_hours) * rule["overhead_factor"]
        estimates[seeds] = {"questions": questions, "signal_per_phase": signal,
                            "filler_per_phase": filler,
                            "pressure_hours": pressure_hours,
                            "low_hours": low_hours,
                            "estimated_inner_hours": total}
    for seeds in rule["allowed_seeds"]:
        if estimates[seeds]["estimated_inner_hours"] <= rule["target_inner_hours"]:
            return seeds, estimates
    return None, estimates


def freeze_p2(rate: float, cohort_variant: str, preview_size: int,
              preview_decision: dict, calibration: dict, live: dict) -> dict:
    seeds, estimates = select_seeds(rate, cohort_variant)
    if seeds is None:
        raise RuntimeError(
            "no pre-declared seed count fits the 15 h inner allocation at "
            f"{rate}/h: {json.dumps(estimates, indent=2)}")
    draft = config.load_p2_draft()
    signal_questions = (config.load_cohort()["counts"]["main_after_preview48"]
                        if cohort_variant == "main_after_preview48"
                        else config.load_cohort()["counts"]["main"])
    frozen = dict(draft)
    frozen.update({
        "status": "ready",
        "p2_authorised": True,
        "signal_questions": signal_questions,
        "seeds": seeds,
        "seed_wall_time_estimates": estimates,
        "arrival_rate_per_hour": rate,
        "preview_pass": preview_decision.get("decision") == "pass",
        "preview_size": preview_size,
        "calibration_rate_per_hour": rate,
        "calibration_band_found": calibration.get("band_found"),
        "calibration_miss_rate": calibration.get("chosen_miss_rate"),
        "live_check_pass": live.get("pass"),
        "main_cohort_variant": cohort_variant,
        "source_lock": "artifacts/source-lock-p2a.json",
        "notes": "Frozen after a passing preview, a calibration band and a passing live manipulation check.",
    })
    entries = traces.build_main(rate, cohort_variant=cohort_variant, seeds=seeds)
    traces.write_manifest(entries)
    config.write_json(config.P2_FROZEN_CONFIG, frozen)
    lock = {
        "created_at": config.utc_now(),
        "stage": "P2A-post-qualification",
        "pool": config.load_pool()["name"],
        "week7_source_lock": config.verify_week7_source_lock(),
        "week8_code": config.code_hashes(),
        "configs": config.config_hashes(),
        "artifacts": config.artifact_hashes(),
        "model": config.load_protocol()["model"],
        "engine": config.load_protocol()["engine"],
        "slo_seconds": config.load_qualify()["slo"]["deadline_seconds"],
        "p2_authorised": True,
        "frozen_config": str(config.P2_FROZEN_CONFIG.relative_to(config.WEEK8_ROOT)),
        "main_traces": {name: entry["sha256"] for name, entry in entries.items()},
    }
    config.write_json(config.SOURCE_LOCK_PATH, lock)
    return frozen


def write_decision(out_dir: Path, go: bool, reason: str,
                   preview: dict | None = None, calibration: dict | None = None,
                   live: dict | None = None, frozen_p2: dict | None = None) -> dict:
    out_dir = Path(out_dir)
    decision = {
        "generated_at": config.utc_now(),
        "go": bool(go),
        "reason": reason,
        "pool": config.load_pool()["name"],
        "preview": preview,
        "calibration": calibration,
        "live_check": live,
        "p2": frozen_p2,
        "p2_config": str(config.P2_FROZEN_CONFIG.relative_to(config.WEEK8_ROOT)) if go else None,
    }
    config.write_json(out_dir / "decision.json", decision)
    lines = ["# Week 8 serving qualification decision", "",
             f"Generated: {decision['generated_at']}", "",
             f"**{'GO' if go else 'STOP'}**", "",
             reason, ""]
    if preview:
        lines += ["## Preview", "",
                  f"Decision: `{preview.get('decision', {}).get('decision')}`", "",
                  "```json",
                  json.dumps(preview.get("decision", {}), indent=2),
                  "```", ""]
    if calibration:
        lines += ["## Calibration", "",
                  f"Chosen rate: `{calibration.get('chosen_rate_per_hour')}` per hour; "
                  f"miss rate `{calibration.get('chosen_miss_rate')}`", ""]
    if live:
        lines += ["## Live check", "",
                  f"Pass: `{live.get('pass')}`; cuts `{live.get('cuts')}`; "
                  f"pressure `{live.get('pressure_fraction')}`", ""]
    (out_dir / ("GO.md" if go else "STOP.md")).write_text("\n".join(lines) + "\n")
    return decision

"""Build the Week 8 preview, calibration and main traces.

All traces reuse the frozen week 7 generators.  The only differences are the
cohort, the declared 240 s SLO for calibration/main, the Week 8 seed base and
the warm-up metadata for calibration.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from larb_week8 import config
from larb_week8.questions import load_merged_questions
from calibrate_load import build_rate_trace
from larb_scaled import workload
from larb_scaled.config import load_protocol


def base_protocol() -> dict:
    protocol = copy.deepcopy(load_protocol())
    protocol["name"] = "larb-week8-omni"
    protocol["seeding"]["seed_base"] = config.load_pool()["seeding"]["seed_base"]
    protocol["seeding"]["question_stride"] = config.load_pool()["seeding"]["question_stride"]
    protocol["deadline"]["slo_seconds"] = config.load_qualify()["slo"]["deadline_seconds"]
    return protocol


def _write_trace(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    return workload.write_trace(path, rows)


def _entry(path: Path, rows: list[dict], **extra) -> dict:
    try:
        file = str(path.relative_to(config.WEEK8_ROOT))
    except ValueError:
        file = str(path)
    return {
        "file": file,
        "sha256": config.digest(path),
        "summary": workload.trace_summary(rows),
        "rows": len(rows),
        **extra,
    }


def build_preview(size: int = 24) -> dict:
    pool = config.load_pool()
    protocol = base_protocol()
    cohort = config.load_cohort()
    questions = load_merged_questions()
    if size == 24:
        name, ids_key = "gate-omni-preview", "preview_ids"
    elif size == 48:
        name, ids_key = "gate-omni-preview48", "preview48_ids"
    else:
        raise ValueError("preview size must be 24 or 48")
    rows = workload.build_gate_trace(name, ids_key, 1, cohort, questions, protocol,
                                     spacing_s=1.5, deadline_s=1800.0)
    path = config.TRACE_DIR / f"{name}.jsonl"
    _write_trace(path, rows)
    return _entry(path, rows, kind="preview", preview_size=size,
                  condition=name, deadline_seconds=1800.0,
                  note="Quality-only preview; no SLO claim.")


def build_calibration(rate: float, minutes: float) -> dict:
    qualify = config.load_qualify()["calibration"]
    protocol = base_protocol()
    cohort = dict(config.load_cohort())
    cohort["screen_ids"] = cohort["calibration_ids"]
    questions = load_merged_questions()
    name = f"gate-omni-cal-{int(rate)}"
    path = config.TRACE_DIR / f"{name}.jsonl"
    rows, sha = build_rate_trace(
        name, path, cohort, questions, protocol, rate_per_hour=rate,
        duration_s=minutes * 60.0, deadline_s=qualify["deadline_seconds"],
        seed=20261116, filler_share=qualify["filler_share"])
    return _entry(path, rows, kind="calibration", condition=name,
                  rate_per_hour=rate, deadline_seconds=qualify["deadline_seconds"],
                  warmup_seconds=qualify["warmup_seconds"],
                  measured_seconds=qualify["measured_seconds"],
                  total_seconds=qualify["total_seconds_per_rate"],
                  sha256_from_builder=sha,
                  note="The first warmup_seconds are excluded from the miss-rate window; the queue is not reset.")


def build_main(rate: float, cohort_variant: str = "main", seeds: int = 4) -> dict:
    qualify = config.load_qualify()
    protocol = base_protocol()
    cohort = config.load_cohort()
    questions = load_merged_questions()
    if cohort_variant == "main":
        main_ids = list(cohort["main_ids"])
    elif cohort_variant == "main_after_preview48":
        main_ids = list(cohort["main_after_preview48_ids"])
    else:
        raise ValueError("cohort_variant must be main or main_after_preview48")
    main_cohort = dict(cohort)
    main_cohort["main_ids"] = main_ids
    protocol["workload"]["filler_share"] = qualify["p2"]["filler_share"]
    protocol["workload"]["conditions"]["low"]["signal_questions"] = 60
    protocol["workload"]["conditions"]["low"]["seeds"] = 2
    for condition in ("sustained", "burst"):
        cfg = protocol["workload"]["conditions"][condition]
        cfg["signal_questions"] = len(main_ids)
        cfg["seeds"] = seeds
        cfg["provisional_rate_per_hour"] = rate
        if condition == "burst":
            cfg["provisional_baseline_per_hour"] = rate
            cfg["recovery_rate_per_hour"] = rate
    entries = {}
    for condition in ("low", "sustained", "burst"):
        rows = workload.build_trace(condition, main_cohort, questions, protocol, seeds=None)
        path = config.TRACE_DIR / f"{condition}.jsonl"
        _write_trace(path, rows)
        entries[condition] = _entry(
            path, rows, kind="main", condition=condition,
            rate_per_hour=(300.0 if condition == "low" else rate),
            deadline_seconds=qualify["slo"]["deadline_seconds"],
            cohort_variant=cohort_variant, seeds=(2 if condition == "low" else seeds),
            note="Main trace; only valid after a passing preview and calibration.",
        )
    return entries


def write_manifest(entries: dict) -> dict:
    path = config.TRACE_DIR / "manifest.json"
    existing = config.read_json(path) if path.exists() else {"traces": {}}
    existing.update({
        "generated_at": config.utc_now(),
        "pool": config.load_pool()["name"],
        "cohort_sha256": config.digest(config.COHORT_PATH),
        "questions_sha256": config.digest(config.QUESTIONS_PATH),
        "seed_base": config.load_pool()["seeding"]["seed_base"],
        "question_stride": config.load_pool()["seeding"]["question_stride"],
        "slo_seconds": config.load_qualify()["slo"]["deadline_seconds"],
        "calibration_warmup_seconds": config.load_qualify()["calibration"]["warmup_seconds"],
    })
    existing.setdefault("traces", {}).update(entries)
    config.write_json(path, existing)
    return existing


def build_all(rates: list[float] | None = None, minutes: float | None = None,
              signal_rate: float | None = None,
              cohort_variant: str = "main", seeds: int = 4) -> dict:
    qualify = config.load_qualify()
    rates = rates or qualify["calibration"]["candidate_rates_per_hour"]
    minutes = minutes or (qualify["calibration"]["total_seconds_per_rate"] / 60.0)
    entries = {
        "gate-omni-preview": build_preview(24),
        "gate-omni-preview48": build_preview(48),
    }
    for rate in rates:
        entry = build_calibration(rate, minutes)
        entries[entry["condition"]] = entry
    if signal_rate is not None:
        entries.update(build_main(signal_rate, cohort_variant=cohort_variant, seeds=seeds))
    return write_manifest(entries)


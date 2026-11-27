"""AIME 2025+2026 candidate pool: paths, protocol, traces, plans and freeze.

CPU-only.  Supplies the trace builders and phase plans for the pre-P2 stages
(240 s calibration, live check) and for P2 on ``aime-2025-2026-v1``; the GPU work
stays in ``runner.run_sequence`` and the frozen analyzers.

Declared pool facts live in ``configs/pool_aime_2025_2026.json`` and the
qualification parameters in ``configs/qualify_aime_v1.json``.  Contract, answer
space (2,048 tokens), window (12,288) and engine settings are the frozen week 7
values; nothing here changes them.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from larb_week8 import config
from larb_scaled import workload
from calibrate_load import build_rate_trace

CANDIDATE = "aime-2025-2026-v1"
ARTIFACT_DIR = config.ARTIFACTS_DIR / "candidates" / CANDIDATE
COHORT_PATH = ARTIFACT_DIR / "cohort.json"
QUESTIONS_PATH = ARTIFACT_DIR / "questions.jsonl"
TRACE_DIR = config.ARTIFACTS_DIR / "traces-candidates"
MANIFEST_PATH = TRACE_DIR / "manifest.json"
QUALIFY_PATH = config.CONFIG_DIR / "qualify_aime_v1.json"
POOL_PATH = config.CONFIG_DIR / "pool_aime_2025_2026.json"
FROZEN_PATH = config.CONFIG_DIR / "p2_main_frozen_aime.json"
SOURCE_LOCK_PATH = config.ARTIFACTS_DIR / "source-lock-p2b.json"


def load_qualify() -> dict:
    return config.read_json(QUALIFY_PATH)


def load_pool() -> dict:
    return config.read_json(POOL_PATH)


def load_cohort() -> dict:
    return config.read_json(COHORT_PATH)


def load_questions() -> dict[str, dict]:
    return config.load_questions(QUESTIONS_PATH)


def calibration_ids() -> list[str]:
    """48 signal questions for the 240 s calibration.

    Declared deviation from P2A: the pool has 60 items, so the calibration
    reuses the 48 preview/escalation questions instead of a disjoint set.
    Calibration scores timeliness and pressure, not accuracy, so reuse does not
    bias the band; the 12 reserve items stay unseen until P2.
    """
    return list(load_cohort()["preview48_ids"])


def main_ids() -> list[str]:
    cohort = load_cohort()
    return list(cohort["preview48_ids"]) + list(cohort["main_ids"])


def protocol(rate: float | None = None, seeds: int = 4) -> dict:
    qualify = load_qualify()
    protocol = copy.deepcopy(config.load_protocol())
    protocol["name"] = CANDIDATE
    protocol["seeding"] = {"seed_base": 900000, "question_stride": 17,
                           "seed_stride": 1}
    protocol["deadline"] = dict(protocol["deadline"],
                                slo_seconds=float(qualify["slo"]["deadline_seconds"]))
    conditions = protocol["workload"]["conditions"]
    conditions["low"] = dict(conditions["low"], signal_questions=len(main_ids()), seeds=2)
    for name in ("sustained", "burst"):
        conditions[name] = dict(conditions[name], signal_questions=len(main_ids()),
                                seeds=seeds)
        if rate is not None:
            conditions[name]["provisional_rate_per_hour"] = rate
            if name == "burst":
                conditions[name]["provisional_baseline_per_hour"] = rate
                conditions[name]["recovery_rate_per_hour"] = rate
    protocol["workload"]["filler_share"] = qualify["p2"]["filler_share"]
    return protocol


def _trace_cohort(signal_ids: list[str]) -> dict:
    """Cohort view for the frozen builders: signal ids plus the week 7 filler."""
    week7 = config.load_week7_cohort()
    ids = list(signal_ids)
    return {"pool": CANDIDATE, "main_ids": ids, "screen_ids": ids,
            "preview_ids": ids, "filler_ids": list(week7["filler_ids"])}


def _rel(path: Path) -> str:
    try:
        return str(Path(path).relative_to(config.WEEK8_ROOT))
    except ValueError:
        return str(path)


def _entry(path: Path, rows: list[dict], **extra) -> dict:
    return {"file": _rel(path),
            "sha256": config.digest(path),
            "summary": workload.trace_summary(rows),
            "rows": len(rows), **extra}


def _write_manifest(entries: dict) -> dict:
    manifest = config.read_json(MANIFEST_PATH) if MANIFEST_PATH.exists() else {"traces": {}}
    manifest.update({"pool": CANDIDATE,
                     "config": _rel(POOL_PATH),
                     "cohort_sha256": config.digest(COHORT_PATH),
                     "questions_sha256": config.digest(QUESTIONS_PATH)})
    manifest.setdefault("traces", {}).update(entries)
    config.write_json(MANIFEST_PATH, manifest)
    return manifest


def calibration_name(rate: float) -> str:
    return f"gate-aime-cal-{int(rate)}"


def build_calibration_traces(rates: list[float], minutes: float = 25.0) -> dict:
    qualify = load_qualify()["calibration"]
    questions = config.load_week7_questions()
    cohort = _trace_cohort(calibration_ids())
    rows_protocol = protocol()
    entries = {}
    for rate in rates:
        name = calibration_name(rate)
        path = TRACE_DIR / f"{name}.jsonl"
        rows, _ = build_rate_trace(
            name, path, cohort, questions, rows_protocol, rate_per_hour=rate,
            duration_s=minutes * 60.0,
            deadline_s=float(qualify["deadline_seconds"]), seed=20261116,
            filler_share=qualify["filler_share"])
        entries[name] = _entry(path, rows, kind="calibration", rate_per_hour=rate,
                               deadline_seconds=qualify["deadline_seconds"],
                               warmup_seconds=qualify["warmup_seconds"],
                               measured_seconds=qualify["measured_seconds"],
                               note="Signal questions are the 48 measured preview items (declared reuse).")
    _write_manifest(entries)
    return entries


def build_seed2_trace() -> dict:
    """Second-seed 48-item trace used for the stability replicate (CPU only)."""
    cohort = load_cohort()
    questions = config.load_week7_questions()
    rows_protocol = protocol()
    rows_protocol["seeding"] = {"seed_base": 910000, "question_stride": 17}
    name = "gate-aime-preview48-s2"
    rows = workload.build_gate_trace(name, "preview48_ids", 1, cohort, questions,
                                     rows_protocol, spacing_s=1.5, deadline_s=1800.0)
    path = TRACE_DIR / f"{name}.jsonl"
    workload.write_trace(path, rows)
    entry = _entry(path, rows, kind="preview-replicate",
                   note="Second-seed stability replicate of the 48-item set.")
    _write_manifest({name: entry})
    return {name: entry}


def calibration_plan(rates: list[float], minutes: float = 25.0) -> list[dict]:
    from larb_week8 import runner
    deadline = float(load_qualify()["slo"]["deadline_seconds"])
    phases = []
    for rate in rates:
        name = calibration_name(rate)
        path = TRACE_DIR / f"{name}.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"missing calibration trace {path}")
        phases.append(runner._phase(f"cal-rate-{int(rate)}", name, "fixed8k",
                                    path, deadline, 600.0))
    return phases


def live_plan(rate: float) -> list[dict]:
    from larb_week8 import runner
    deadline = float(load_qualify()["slo"]["deadline_seconds"])
    path = TRACE_DIR / f"{calibration_name(rate)}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"missing calibration trace {path}")
    return [runner._phase(f"live-{int(rate)}", calibration_name(rate), "live",
                          path, deadline, 600.0)]


def seed_estimates(rate: float) -> dict:
    rule = load_qualify()["p2"]["wall_time_rule"]
    questions = len(main_ids())
    filler_share = load_qualify()["p2"]["filler_share"]
    low_hours = (rule["low_control_requests_per_arm"] * rule["low_arms"]
                 / rule["low_rate_per_hour"])
    estimates = {}
    for seeds in rule["allowed_seeds"]:
        signal = questions * seeds
        filler = math.ceil(signal * filler_share / 0.70)
        per_phase = signal + filler
        pressure = rule["pressure_phases"] * per_phase / rate
        total = (pressure + low_hours) * rule["overhead_factor"]
        estimates[seeds] = {"questions": questions, "signal_per_phase": signal,
                            "filler_per_phase": filler, "pressure_hours": pressure,
                            "low_hours": low_hours,
                            "estimated_inner_hours": total}
    return estimates


def select_seeds(rate: float) -> tuple[int | None, dict]:
    rule = load_qualify()["p2"]["wall_time_rule"]
    estimates = seed_estimates(rate)
    for seeds in rule["allowed_seeds"]:
        if estimates[seeds]["estimated_inner_hours"] <= rule["target_inner_hours"]:
            return seeds, estimates
    return None, estimates


def build_main_traces(rate: float, seeds: int) -> dict:
    qualify = load_qualify()
    questions = config.load_week7_questions()
    cohort = _trace_cohort(main_ids())
    rows_protocol = protocol(rate=rate, seeds=seeds)
    entries = {}
    for condition in ("low", "sustained", "burst"):
        rows = workload.build_trace(condition, cohort, questions, rows_protocol,
                                    seeds=None)
        path = TRACE_DIR / f"{condition}.jsonl"
        workload.write_trace(path, rows)
        entries[condition] = _entry(
            path, rows, kind="main", condition=condition,
            rate_per_hour=rows_protocol["workload"]["conditions"][condition].get(
                "provisional_rate_per_hour", rate),
            deadline_seconds=qualify["slo"]["deadline_seconds"],
            seeds=(2 if condition == "low" else seeds))
    _write_manifest(entries)
    return entries


def freeze(rate: float, calibration: dict, live: dict) -> dict:
    seeds, estimates = select_seeds(rate)
    if seeds is None:
        raise RuntimeError(f"no declared seed count fits the inner budget at {rate}/h: "
                           f"{estimates}")
    qualify = load_qualify()
    entries = build_main_traces(rate, seeds)
    packet = {
        "schema_version": 1,
        "name": "larb-week8-p2-aime-frozen",
        "status": "ready",
        "p2_authorised": True,
        "pool": CANDIDATE,
        "pool_config": _rel(POOL_PATH),
        "qualify_config": _rel(QUALIFY_PATH),
        "outer_hours": qualify["p2"]["outer_hours"],
        "inner_hours": qualify["p2"]["inner_hours"],
        "arms": qualify["p2"]["arms"],
        "conditions": qualify["p2"]["conditions"],
        "orders": qualify["p2"]["orders"],
        "signal_questions": len(main_ids()),
        "seeds": seeds,
        "seed_wall_time_estimates": estimates,
        "filler_share": qualify["p2"]["filler_share"],
        "deadline_seconds": qualify["slo"]["deadline_seconds"],
        "drain_allowance_seconds": qualify["p2"]["drain_allowance_seconds"],
        "max_num_seqs": qualify["frozen_rig"]["max_num_seqs"],
        "answer_contract": qualify["frozen_rig"]["answer_contract"],
        "answer_cap_tokens": qualify["frozen_rig"]["answer_cap_tokens"],
        "enforce_eager": qualify["frozen_rig"]["enforce_eager"],
        "pressure_threshold": qualify["frozen_rig"]["pressure_threshold"],
        "pressure_persistence_steps": qualify["frozen_rig"]["pressure_persistence_steps"],
        "arrival_rate_per_hour": rate,
        "calibration_rate_per_hour": rate,
        "calibration_miss_rate": calibration.get("chosen_miss_rate"),
        "calibration_band_found": calibration.get("band_found"),
        "live_check_pass": live.get("pass"),
        "preview_gate": qualify["preview"]["gate_design"],
        "preview_authorisation": qualify["preview"]["authorisation"]["decision"],
        "main_cohort_variant": "aime_all_60",
        "main_traces": {name: entry["sha256"] for name, entry in entries.items()},
        "notes": ("Frozen after the authorised preview, a calibration band and a passing live "
                  "check. Contract, answer space and window are the frozen week 7 values."),
    }
    config.write_json(FROZEN_PATH, packet)
    lock = {
        "created_at": config.utc_now(),
        "stage": "P2B-post-calibration",
        "pool": CANDIDATE,
        "week7_source_lock": config.verify_week7_source_lock(),
        "week8_code": config.code_hashes(),
        "configs": config.config_hashes(),
        "artifacts": config.artifact_hashes(),
        "candidate_cohort_sha256": config.digest(COHORT_PATH),
        "candidate_questions_sha256": config.digest(QUESTIONS_PATH),
        "main_traces": packet["main_traces"],
        "slo_seconds": qualify["slo"]["deadline_seconds"],
        "p2_authorised": True,
        "frozen_config": _rel(FROZEN_PATH),
    }
    config.write_json(SOURCE_LOCK_PATH, lock)
    return packet


def main_plan() -> list[dict]:
    from larb_week8 import runner
    if not FROZEN_PATH.exists():
        raise FileNotFoundError(f"{FROZEN_PATH.name} is missing; run the freeze stage first")
    packet = config.read_json(FROZEN_PATH)
    if not packet.get("p2_authorised"):
        raise RuntimeError("P2 is not authorised in the frozen packet")
    phases = []
    for condition in packet["conditions"]:
        path = TRACE_DIR / f"{condition}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        summary = workload.trace_summary(rows)
        expected_seeds = 2 if condition == "low" else packet["seeds"]
        if summary["signal_questions"] != len(main_ids()):
            raise RuntimeError(f"{condition} trace has {summary['signal_questions']} "
                               f"questions, packet expects {len(main_ids())}")
        if summary["seeds_per_question"] != expected_seeds:
            raise RuntimeError(f"{condition} trace has {summary['seeds_per_question']} "
                               f"seeds/question, packet expects {expected_seeds}")
        for arm in packet["orders"][condition]:
            phases.append(runner._phase(
                f"main-{condition}-{arm}", condition, arm, path,
                float(packet["deadline_seconds"]),
                float(packet["drain_allowance_seconds"]),
                env={"LARB_MAX_NUM_SEQS": packet["max_num_seqs"],
                     "LARB_THRESHOLD": packet["pressure_threshold"]}))
    return phases


def prompt_margin() -> dict:
    """Context margin for the candidate prompts at the frozen 8k request shape."""
    rig = load_qualify()["frozen_rig"]
    counts = config.read_json(config.WEEK7_ROOT / "data/processed/prompt-token-counts.json")
    tokens = [counts[qid] for qid in main_ids() if qid in counts]
    cue_tokens = 14  # legacy cue length, checked by the transition check
    reserve = rig["budgets"]["long"] + cue_tokens + rig["answer_cap_tokens"] + 2
    biggest = max(tokens) if tokens else None
    return {"questions": len(tokens), "max_prompt_tokens": biggest,
            "reserved_tokens": reserve, "window": rig["max_model_len"],
            "margin_tokens": (rig["max_model_len"] - reserve - biggest)
            if biggest is not None else None}





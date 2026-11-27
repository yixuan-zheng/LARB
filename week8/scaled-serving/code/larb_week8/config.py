"""Paths, frozen configuration loading and hashing for the Week 8 layer."""
from __future__ import annotations

import json
from pathlib import Path

from larb_week8 import (REPO_ROOT, WEEK7_CODE, WEEK7_ROOT, WEEK8_CODE,
                        WEEK8_ROOT)
from larb_scaled import config as frozen_config

CONFIG_DIR = WEEK8_ROOT / "configs"
DATA_DIR = WEEK8_ROOT / "data"
ARTIFACTS_DIR = WEEK8_ROOT / "artifacts"
RESULTS_DIR = WEEK8_ROOT / "results"
REPORTS_DIR = WEEK8_ROOT / "reports"
LOGS_DIR = WEEK8_ROOT / "logs"
TRACE_DIR = ARTIFACTS_DIR / "traces"

POOL_CONFIG = CONFIG_DIR / "pool_omni.json"
QUALIFY_CONFIG = CONFIG_DIR / "qualify.json"
P2_DRAFT_CONFIG = CONFIG_DIR / "p2_main_draft.json"
P2_FROZEN_CONFIG = CONFIG_DIR / "p2_main_frozen.json"
COHORT_PATH = ARTIFACTS_DIR / "cohort.json"
QUESTIONS_PATH = DATA_DIR / "processed/questions.jsonl"
POOL_MANIFEST_PATH = DATA_DIR / "processed/manifest.json"
SOURCE_LOCK_PATH = ARTIFACTS_DIR / "source-lock-p2a.json"
WEEK7_QUESTIONS_PATH = WEEK7_ROOT / "data/processed/questions.jsonl"
WEEK7_COHORT_PATH = WEEK7_ROOT / "artifacts/cohort.json"
WEEK7_SOURCE_LOCK_PATH = WEEK7_ROOT / "artifacts/source-lock-p1.json"

read_json = frozen_config.read_json
write_json = frozen_config.write_json
digest = frozen_config.digest
utc_now = frozen_config.utc_now
load_protocol = frozen_config.load_protocol


def load_pool() -> dict:
    return read_json(POOL_CONFIG)


def load_qualify() -> dict:
    return read_json(QUALIFY_CONFIG)


def load_p2_draft() -> dict:
    return read_json(P2_DRAFT_CONFIG)


def load_cohort() -> dict:
    return read_json(COHORT_PATH)


def load_questions(path: Path | None = None) -> dict[str, dict]:
    path = Path(path or QUESTIONS_PATH)
    rows = {}
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                row = json.loads(line)
                rows[row["question_id"]] = row
    return rows


def load_week7_questions() -> dict[str, dict]:
    return load_questions(WEEK7_QUESTIONS_PATH)


def merged_questions() -> dict[str, dict]:
    """Week 8 signal questions plus the frozen week 7 filler questions.

    The filler pool is reused by ID so its text is not duplicated.  A duplicate
    question ID is an error, not a silent overwrite.
    """
    week7 = load_week7_questions()
    week8 = load_questions()
    overlap = set(week7) & set(week8)
    if overlap:
        raise ValueError(f"duplicate question ids across week7/week8: {sorted(overlap)[:5]}")
    return {**week7, **week8}


def load_week7_cohort() -> dict:
    return read_json(WEEK7_COHORT_PATH)


def config_hashes() -> dict[str, str]:
    return {str(path.relative_to(WEEK8_ROOT)): digest(path)
            for path in sorted(CONFIG_DIR.glob("*.json"))}


def code_hashes() -> dict[str, str]:
    paths = sorted((WEEK8_ROOT / "code").rglob("*.py"))
    return {str(path.relative_to(WEEK8_ROOT)): digest(path) for path in paths}


def frozen_week7_code_hashes() -> dict[str, str]:
    paths = sorted((WEEK7_ROOT / "code").rglob("*.py"))
    return {str(path.relative_to(WEEK7_ROOT)): digest(path) for path in paths}


def artifact_hashes() -> dict[str, str]:
    paths = []
    for folder in (DATA_DIR / "processed", TRACE_DIR):
        if folder.exists():
            paths.extend(sorted(path for path in folder.glob("*")
                                if path.is_file() and path.name != "manifest.json"))
    for extra in (COHORT_PATH,):
        if extra.exists():
            paths.append(extra)
    return {str(path.relative_to(WEEK8_ROOT)): digest(path) for path in paths}


def verify_week7_source_lock() -> dict:
    """Fail if the frozen week 7 code no longer matches its P1 source lock."""
    lock = read_json(WEEK7_SOURCE_LOCK_PATH)
    expected = lock.get("code", {})
    current = frozen_week7_code_hashes()
    missing = sorted(set(expected) - set(current))
    changed = sorted(path for path in expected if path in current and expected[path] != current[path])
    if missing or changed:
        raise RuntimeError(
            "week7 source lock no longer matches the checked-out code: "
            f"missing={missing} changed={changed}"
        )
    return {"ok": True, "files": len(current),
            "source_lock_sha256": digest(WEEK7_SOURCE_LOCK_PATH)}

"""Build the pre-declared AIME 2025+2026 candidate pool and its preview traces.

Selected after the longitudinal slope analysis (reports/SLOPE-ANALYSIS.md):
AIME is the only family with positive 4k->8k evidence in the rig (2023 +29.2
points on 24 items, 2025 +13.4 points on 60 responses), while HMMT and
Omni-MATH are flat.  AIME 2026 is the only fresh, untested AIME pool in the
frozen week 7 question set.

Nothing is measured here: the pool, the split and the seed base are written to
configs/pool_aime_2025_2026.json before any GPU request.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from larb_week8 import config
from larb_scaled import workload

CANDIDATE = "aime-2025-2026-v1"
SALT = "larb-week8-aime-candidate-v1"
SEED_BASE = 900000
STRIDE = 17
SOURCES = ("MathArena/aime_2025", "MathArena/aime_2026")
# Cohort and questions live under artifacts/ so the handoff runs from tracked
# files; the builder stays idempotent and refuses a moved source hash upstream.
OUT_DIR = config.ARTIFACTS_DIR / "candidates" / CANDIDATE
TRACE_DIR = config.ARTIFACTS_DIR / "traces-candidates"
CONFIG_PATH = config.CONFIG_DIR / "pool_aime_2025_2026.json"


def _rank(questions: dict[str, dict], source: str) -> list[str]:
    ids = [qid for qid, q in questions.items() if q.get("pool") == source]
    return sorted(ids, key=lambda qid: hashlib.sha256(f"{SALT}:{qid}".encode()).hexdigest())


def main() -> dict:
    questions = config.load_week7_questions()
    ranked = {source: _rank(questions, source) for source in SOURCES}
    for source, ids in ranked.items():
        if len(ids) < 24:
            raise RuntimeError(f"{source} has only {len(ids)} eligible items")
    # 12 items per year in the 24-item preview, the next 12 per year in the
    # 48-item escalation, the remaining 6 per year held as the main cohort.
    preview = ranked[SOURCES[0]][:12] + ranked[SOURCES[1]][:12]
    escalation = ranked[SOURCES[0]][12:24] + ranked[SOURCES[1]][12:24]
    reserve = ranked[SOURCES[0]][24:] + ranked[SOURCES[1]][24:]
    cohort = {
        "pool": CANDIDATE,
        "preview_ids": preview,
        "escalation_ids": escalation,
        "preview48_ids": preview + escalation,
        "main_ids": reserve,
        "counts": {"preview": 24, "escalation": 24, "preview48": 48, "reserve": len(reserve)},
        "selection": ("12 hash-ranked items per source in the preview, the next 12 per "
                      "source in the escalation; salt=" + SALT),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "questions.jsonl").write_text(
        "".join(json.dumps(questions[qid], ensure_ascii=False) + "\n"
                for qid in preview + escalation + reserve))
    config.write_json(OUT_DIR / "cohort.json", cohort)

    pool = {
        "schema_version": 1,
        "name": CANDIDATE,
        "status": "predeclared before measurement",
        "dataset": "MathArena AIME 2025 and AIME 2026, frozen week 7 question set",
        "sources": list(SOURCES),
        "exposure": {"MathArena/aime_2025": "exposed", "MathArena/aime_2026": "fresh"},
        "why": ("AIME is the only family with positive 4k->8k evidence in this rig; "
                "AIME 2026 is fresh and has never been used as a slope pool."),
        "filters": {"inherited": "week 7 P0 exclusion rules and self-gradable references",
                    "answer_type": "integer", "selection": cohort["selection"]},
        "counts": cohort["counts"],
        "seeding": {"seed_base": SEED_BASE, "question_stride": STRIDE,
                    "preview_seed_index": 0},
        "preview": {"size": 24, "escalation_size": 48, "spacing_seconds": 1.5,
                    "deadline_seconds": 1800.0,
                    "rule": "configs/qualify.json preview pass / near-miss / stop, unchanged"},
        "traces": {"preview": str((TRACE_DIR / "gate-aime-preview.jsonl").relative_to(config.WEEK8_ROOT)),
                   "preview48": str((TRACE_DIR / "gate-aime-preview48.jsonl").relative_to(config.WEEK8_ROOT))},
    }
    config.write_json(CONFIG_PATH, pool)

    protocol = dict(config.load_protocol())
    protocol["name"] = CANDIDATE
    protocol["seeding"] = {"seed_base": SEED_BASE, "question_stride": STRIDE}
    protocol["deadline"] = dict(protocol["deadline"], slo_seconds=1800.0)
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    entries = {}
    for size, ids_key in ((24, "preview_ids"), (48, "preview48_ids")):
        name = "gate-aime-preview" if size == 24 else "gate-aime-preview48"
        rows = workload.build_gate_trace(name, ids_key, 1, cohort, questions, protocol,
                                         spacing_s=1.5, deadline_s=1800.0)
        path = TRACE_DIR / f"{name}.jsonl"
        sha = workload.write_trace(path, rows)
        entries[name] = {"file": str(path.relative_to(config.WEEK8_ROOT)), "sha256": sha,
                         "summary": workload.trace_summary(rows),
                         "sources": sorted({row["source"] for row in rows}),
                         "exposure": sorted({row["exposure"] for row in rows})}
    config.write_json(TRACE_DIR / "manifest.json",
                      {"pool": CANDIDATE, "config": str(CONFIG_PATH.relative_to(config.WEEK8_ROOT)),
                       "cohort_sha256": config.digest(OUT_DIR / "cohort.json"),
                       "traces": entries})
    print(json.dumps({"config": str(CONFIG_PATH), "cohort": cohort["counts"],
                      "traces": {k: v["summary"]["requests"] for k, v in entries.items()}},
                     indent=2))
    return entries


if __name__ == "__main__":
    main()

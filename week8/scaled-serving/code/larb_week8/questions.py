"""Question loading shared by the Week 8 server wrapper and trace builder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from larb_week8 import config


def load_week8_questions() -> dict[str, dict]:
    return config.load_questions()


def load_merged_questions() -> dict[str, dict]:
    """Week 8 signal questions plus the frozen week 7 filler questions."""
    week7 = config.load_week7_questions()
    week8 = load_week8_questions()
    overlap = set(week7) & set(week8)
    if overlap:
        raise ValueError(f"duplicate question ids across week7/week8: {sorted(overlap)[:5]}")
    return {**week7, **week8}


def validate_question_set(questions: dict[str, dict], question_ids: list[str]) -> dict:
    missing = [qid for qid in question_ids if qid not in questions]
    if missing:
        raise ValueError(f"missing question ids: {missing[:5]}")
    bad_hashes = []
    for qid in question_ids:
        question = questions[qid]
        expected = hashlib.sha256(question["prompt"].encode("utf-8")).hexdigest()
        if expected != question.get("prompt_sha256"):
            bad_hashes.append(qid)
    if bad_hashes:
        raise ValueError(f"prompt hash mismatch: {bad_hashes[:5]}")
    return {"ok": True, "questions": len(question_ids)}


def write_merged_view(path: Path) -> dict:
    """Write a merged JSONL view for tools that need one file.

    This is a derived view, not a second source of truth; the week 7 filler
    text remains owned by the frozen week 7 manifest.
    """
    questions = load_merged_questions()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for qid in sorted(questions):
            handle.write(json.dumps(questions[qid], ensure_ascii=False) + "\n")
    return {"path": str(path), "questions": len(questions)}

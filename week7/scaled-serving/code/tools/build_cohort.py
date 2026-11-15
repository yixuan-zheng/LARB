#!/usr/bin/env python3
"""Normalize fetched datasets, apply exclusions, and freeze the cohort.

Run with the serving Python (it has transformers) from the repository root:
    PYTHONPATH=week7/scaled-serving/code \
      /storage/.../venv/bin/python week7/scaled-serving/code/tools/build_cohort.py
"""
import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from larb_scaled import config, datasets  # noqa: E402


def token_counts(questions, model_path):
    """Fast local token count without importing transformers/torch.

    Adds a fixed 32-token allowance for the chat template and generation prompt.
    The server performs the exact template check at runtime; this count is only
    for the prompt-length exclusion.
    """
    try:
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(Path(model_path) / "tokenizer.json"))
        encode = lambda text: len(tokenizer.encode(text, add_special_tokens=False).ids) + 32
    except Exception:
        encode = lambda text: max(1, len(text) // 4)
    counts = {}
    for question in questions:
        counts[question["question_id"]] = encode(question["prompt"]) if question.get("prompt") else None
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--salt", default="larb-scaled-v1")
    parser.add_argument("--preview", type=int, default=24)
    parser.add_argument("--screen-aime", type=int, default=24)
    parser.add_argument("--screen-hmmt", type=int, default=24)
    parser.add_argument("--filler", type=int, default=200)
    parser.add_argument("--model", default=os.environ.get("LARB_MODEL_PATH",
                        config.load_protocol()["model"]["local_path_default"]))
    parser.add_argument("--no-tokenizer", action="store_true")
    args = parser.parse_args()

    config.DATA_DIR.joinpath("processed").mkdir(parents=True, exist_ok=True)
    config.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    questions = datasets.build_all_questions()
    if args.no_tokenizer:
        counts = {q["question_id"]: max(1, len(q["prompt"]) // 4) for q in questions}
    else:
        counts = token_counts(questions, args.model)
    config.write_json(config.DATA_DIR / "processed/prompt-token-counts.json", counts)
    kept, excluded = datasets.mark_exclusions(questions, counts)
    datasets.validate_questions(questions)
    datasets.write_questions(questions)
    cohort = datasets.select_cohort(questions, salt=args.salt, preview_size=args.preview,
                                    screen_aime=args.screen_aime,
                                    screen_hmmt=args.screen_hmmt,
                                    filler_size=args.filler)
    cohort["raw_manifest_sha256"] = config.digest(config.DATA_DIR / "raw/manifest.json")
    cohort["questions_sha256"] = config.digest(config.DATA_DIR / "processed/questions.jsonl")
    cohort["prompt_tokens_max"] = max(v for v in counts.values() if v is not None)
    config.write_json(config.ARTIFACTS_DIR / "cohort.json", cohort)
    config.write_json(config.DATA_DIR / "processed/exclusions.json",
                      {"count": len(excluded), "excluded": excluded})
    by_pool = Counter(q["pool"] for q in questions if q["eligible"])
    by_role = Counter(q["role"] for q in questions if q["eligible"])
    summary = {
        "generated_at": config.utc_now(),
        "raw_rows": len(questions),
        "eligible": len(kept),
        "excluded": len(excluded),
        "eligible_by_role": dict(sorted(by_role.items())),
        "eligible_by_pool": dict(sorted(by_pool.items())),
        "cohort_counts": cohort["counts"],
        "exclusions_by_reason": dict(Counter(item["reason"] for item in excluded)),
        "questions_sha256": cohort["questions_sha256"],
        "raw_manifest_sha256": cohort["raw_manifest_sha256"],
    }
    config.write_json(config.DATA_DIR / "processed/manifest.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

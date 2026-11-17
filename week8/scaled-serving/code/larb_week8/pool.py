"""Build the pre-declared Omni-MATH fallback pool, CPU-only.

The builder uses the frozen week 7 extraction/grading code for the
self-gradability check and the week 7 exclusion rules for proof/diagram/
multiple-choice/prompt-length QC.  It never calls a model and never filters on
an observed Qwen3-4B outcome.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from larb_week8 import config
from larb_scaled import datasets, grading

USER_AGENT = "larb-week8-pool/1.0"


def _hash_rank(question_id: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{question_id}".encode()).hexdigest()


def _normalise_space(text: str) -> str:
    return datasets.normalise_space(text)


def download_source(pool: dict, force: bool = False) -> Path:
    target = config.DATA_DIR / "raw" / pool["slug"] / pool["source_file"]
    if target.exists() and not force:
        actual = config.digest(target)
        if actual != pool["source_sha256"]:
            raise RuntimeError(
                f"existing {target} hash {actual} does not match the frozen "
                f"{pool['source_sha256']}; pass --force only to refetch"
            )
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(pool["source_url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = response.read()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != pool["source_sha256"]:
        raise RuntimeError(
            f"downloaded source hash {actual} does not match the frozen "
            f"{pool['source_sha256']}; the dataset revision moved"
        )
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(target)
    meta = {
        "dataset": pool["dataset"],
        "slug": pool["slug"],
        "revision": pool["revision"],
        "license": pool["license"],
        "source_url": pool["source_url"],
        "source_file": str(target.relative_to(config.WEEK8_ROOT)),
        "source_sha256": actual,
        "source_bytes": len(payload),
        "row_count": sum(1 for line in payload.splitlines() if line.strip()),
        "fetched_at": config.utc_now(),
        "note": "Frozen source bytes; the file is gitignored and re-verified by hash.",
    }
    config.write_json(target.parent / "meta.json", meta)
    return target


def load_rows(pool: dict) -> list[dict]:
    path = config.DATA_DIR / "raw" / pool["slug"] / pool["source_file"]
    rows = []
    with path.open() as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    if len(rows) != pool["expected_rows"]:
        raise ValueError(f"expected {pool['expected_rows']} rows, found {len(rows)}")
    return rows


def _tokenizer():
    from tokenizers import Tokenizer
    from larb_scaled.config import load_protocol
    import os
    model = os.environ.get("LARB_MODEL_PATH",
                           load_protocol()["model"]["local_path_default"])
    return Tokenizer.from_file(str(Path(model) / "tokenizer.json"))


def _token_count(tokenizer, prompt: str) -> int:
    # The week 7 P0 builder uses a 32-token allowance for the chat template.
    return len(tokenizer.encode(prompt, add_special_tokens=False).ids) + 32


def _self_gradable(answer: str) -> bool:
    """Can the frozen boxed extractor + exact matcher grade the reference?"""
    result = grading.grade("\\boxed{" + answer + "}", answer, use_math_verify=False)
    return bool(result["correct"])


def normalise_row(row: dict, index: int, pool: dict) -> dict:
    problem = _normalise_space(row.get("problem", ""))
    answer = str(row.get("answer", "")).strip()
    prompt = datasets.prompt_for(problem) if problem else ""
    question_id = f"{pool['question_id_prefix']}-{index:04d}"
    return {
        "question_id": question_id,
        "role": "main",
        "pool": pool["dataset"],
        "pool_slug": pool["slug"],
        "source_row": index,
        "source_revision": pool["revision"],
        "source": row.get("source"),
        "domain": row.get("domain"),
        "difficulty": float(row.get("difficulty")),
        "exposure": pool["exposure"],
        "exposure_note": pool["exposure_note"],
        "declared_answer_type": "expression",
        "answer_type": "integer" if answer.lstrip("-").isdigit() else "expression",
        "problem": problem,
        "answer": answer,
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else None,
        "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
    }


def candidate_rows(rows: list[dict], pool: dict) -> tuple[list[dict], list[dict]]:
    tokenizer = _tokenizer()
    filters = pool["filters"]
    candidates, excluded = [], []
    seen_problems = {}
    for index, row in enumerate(rows):
        question = normalise_row(row, index, pool)
        reason = None
        if not question["problem"]:
            reason = "missing_problem"
        elif not question["answer"]:
            reason = "missing_answer"
        elif not (filters["difficulty_min"] <= question["difficulty"] <= filters["difficulty_max"]):
            reason = "difficulty_outside_band"
        elif len(question["answer"]) > filters["answer_max_chars"]:
            reason = "answer_too_long_for_budget"
        elif filters.get("exclude_text_answers") and "\\text{" in question["answer"]:
            reason = "text_answer"
        else:
            tokens = _token_count(tokenizer, question["prompt"])
            question["prompt_tokens"] = tokens
            if tokens > filters["prompt_max_tokens"]:
                reason = "prompt_too_long"
            else:
                reason = datasets.exclusion_reason(question, tokens)
                if reason is None and filters.get("require_self_gradable"):
                    if not _self_gradable(question["answer"]):
                        reason = "reference_not_self_gradable"
                if reason is None:
                    key = _normalise_space(question["problem"]).lower()
                    if key in seen_problems:
                        reason = f"duplicate_of:{seen_problems[key]}"
                    else:
                        seen_problems[key] = question["question_id"]
        question["eligible"] = reason is None
        question["exclusion"] = reason
        if reason is None:
            candidates.append(question)
        else:
            excluded.append({"question_id": question["question_id"],
                             "source": question["source"],
                             "difficulty": question["difficulty"],
                             "reason": reason})
    return candidates, excluded


def _select_stratum(candidates: list[dict], target: int, cap: int,
                    salt: str) -> tuple[list[dict], dict]:
    """Round-robin across sources with a per-source cap; deterministic."""
    by_source = defaultdict(list)
    for question in candidates:
        by_source[question["source"]].append(question)
    for source in by_source:
        by_source[source].sort(key=lambda q: (_hash_rank(q["question_id"], salt),
                                               q["question_id"]))
    selected = []
    cursor = defaultdict(int)
    sources = sorted(by_source, key=lambda source: (by_source[source][0]["question_id"], source))
    while len(selected) < target:
        progressed = False
        for source in sources:
            if len(selected) >= target:
                break
            index = cursor[source]
            if index >= len(by_source[source]) or index >= cap:
                continue
            selected.append(by_source[source][index])
            cursor[source] += 1
            progressed = True
        if not progressed:
            break
    if len(selected) < target:
        # Pre-declared relaxation: fill from the remaining hash-ranked items,
        # ignoring the per-source cap but keeping the same deterministic order.
        selected_ids = {q["question_id"] for q in selected}
        remaining = [q for q in candidates if q["question_id"] not in selected_ids]
        remaining.sort(key=lambda q: (_hash_rank(q["question_id"], salt), q["question_id"]))
        selected.extend(remaining[:target - len(selected)])
        relaxation = True
    else:
        relaxation = False
    return selected, {
        "target": target,
        "selected": len(selected),
        "sources": len({q["source"] for q in selected}),
        "source_cap": cap,
        "cap_relaxed": relaxation,
        "top_sources": Counter(q["source"] for q in selected).most_common(10),
    }


def build_cohort(candidates: list[dict], pool: dict) -> tuple[dict, dict]:
    selected, strata_meta = [], {}
    for stratum in pool["strata"]:
        subset = [q for q in candidates
                  if stratum["min_inclusive"] <= q["difficulty"] < stratum["max_exclusive"]]
        chosen, meta = _select_stratum(subset, stratum["target"],
                                       pool["source_cap_per_stratum"],
                                       f"{pool['salt']}:{stratum['name']}")
        for question in chosen:
            question["stratum"] = stratum["name"]
        selected.extend(chosen)
        strata_meta[stratum["name"]] = meta
    if len(selected) != sum(stratum["target"] for stratum in pool["strata"]):
        raise ValueError(f"cohort size {len(selected)} does not match the declared targets")

    preview, main, escalation = [], [], []
    preview_meta = {}
    for stratum in pool["strata"]:
        members = [q for q in selected if q["stratum"] == stratum["name"]]
        members.sort(key=lambda q: (_hash_rank(q["question_id"], f"{pool['salt']}:preview"),
                                    q["question_id"]))
        p = members[:pool["preview"]["per_stratum"]]
        rest = members[pool["preview"]["per_stratum"]:]
        rest.sort(key=lambda q: (_hash_rank(q["question_id"], f"{pool['salt']}:preview48"),
                                 q["question_id"]))
        e = rest[:pool["preview"]["escalation_per_stratum"]]
        preview.extend(p)
        escalation.extend(e)
        main.extend(rest)
        preview_meta[stratum["name"]] = {"preview": len(p), "escalation": len(e),
                                         "main": len(rest)}
    main_ids = [q["question_id"] for q in main]
    escalation_ids = {q["question_id"] for q in escalation}
    main_after_preview48 = [qid for qid in main_ids if qid not in escalation_ids]
    preview_ids = [q["question_id"] for q in preview]
    preview48_ids = preview_ids + [q["question_id"] for q in escalation]

    # Calibration uses an equal share of each stratum from the cohort that
    # survives the optional 48-item escalation, so the calibration set is
    # always a subset of the eventual main cohort.
    by_id = {q["question_id"]: q for q in selected}
    calibration, calibration_meta = [], {}
    take = pool["calibration"]["signal_questions"] // len(pool["strata"])
    for stratum in pool["strata"]:
        ids = [qid for qid in main_after_preview48 if by_id[qid]["stratum"] == stratum["name"]]
        ids.sort(key=lambda qid: (_hash_rank(qid, f"{pool['salt']}:calibration"), qid))
        calibration.extend(ids[:take])
        calibration_meta[stratum["name"]] = take
    if len(calibration) != pool["calibration"]["signal_questions"]:
        raise ValueError("calibration selection does not match the declared size")
    if set(calibration) & set(preview_ids):
        raise ValueError("calibration and preview overlap")

    week7_cohort = config.load_week7_cohort()
    cohort = {
        "schema_version": 1,
        "pool": pool["name"],
        "dataset": pool["dataset"],
        "revision": pool["revision"],
        "salt": pool["salt"],
        "counts": {
            "signal_pool": len(candidates),
            "selected": len(selected),
            "preview": len(preview_ids),
            "preview48": len(preview48_ids),
            "main": len(main_ids),
            "main_after_preview48": len(main_after_preview48),
            "calibration": len(calibration),
            "filler": len(week7_cohort["filler_ids"]),
        },
        "main_ids": main_ids,
        "main_after_preview48_ids": main_after_preview48,
        "preview_ids": preview_ids,
        "preview48_ids": preview48_ids,
        "escalation_ids": sorted(escalation_ids),
        "calibration_ids": calibration,
        "filler_ids": list(week7_cohort["filler_ids"]),
        "strata": strata_meta,
        "preview_strata": preview_meta,
        "calibration_strata": calibration_meta,
        "notes": [
            "All signal items are from the Omni-MATH fallback pool and are tagged exposed.",
            "Preview ids are excluded from both main variants.",
            "The optional 48-item preview adds the escalation ids and removes them from main.",
            "Filler ids are reused from the frozen week 7 cohort; their question text lives in week 7.",
        ],
    }
    return cohort, {"selected": selected, "preview": preview, "escalation": escalation}



def write_pool(questions: list[dict], cohort: dict, pool: dict,
               excluded: list[dict], raw_path: Path) -> dict:
    config.QUESTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    questions = sorted(questions, key=lambda q: q["question_id"])
    with config.QUESTIONS_PATH.open("w") as handle:
        for question in questions:
            handle.write(json.dumps(question, ensure_ascii=False) + "\n")
    config.write_json(config.COHORT_PATH, cohort)
    token_counts = {q["question_id"]: q.get("prompt_tokens") for q in questions}
    config.write_json(config.DATA_DIR / "processed/prompt-token-counts.json", token_counts)
    manifest = {
        "generated_at": config.utc_now(),
        "pool": pool["name"],
        "dataset": pool["dataset"],
        "revision": pool["revision"],
        "license": pool["license"],
        "raw_source": str(raw_path.relative_to(config.WEEK8_ROOT)),
        "raw_sha256": config.digest(raw_path),
        "source_rows": pool["expected_rows"],
        "filters": pool["filters"],
        "candidate_counts": dict(Counter(q["stratum"] for q in questions)),
        "excluded": len(excluded),
        "excluded_by_reason": dict(Counter(item["reason"] for item in excluded)),
        "cohort_counts": cohort["counts"],
        "difficulty": {
            "min": min(q["difficulty"] for q in questions),
            "max": max(q["difficulty"] for q in questions),
            "mean": sum(q["difficulty"] for q in questions) / len(questions),
        },
        "sources": dict(Counter(q["source"] for q in questions)),
        "answer_types": dict(Counter(q["answer_type"] for q in questions)),
        "questions_sha256": config.digest(config.QUESTIONS_PATH),
        "cohort_sha256": config.digest(config.COHORT_PATH),
        "seed_base": pool["seeding"]["seed_base"],
        "question_stride": pool["seeding"]["question_stride"],
        "note": "Built CPU-only; no Qwen3-4B outcome was used to include or exclude an item.",
    }
    config.write_json(config.POOL_MANIFEST_PATH, manifest)
    return manifest


def build_pool(force: bool = False) -> dict:
    pool = config.load_pool()
    raw_path = download_source(pool, force=force)
    rows = load_rows(pool)
    candidates, excluded = candidate_rows(rows, pool)
    if len(candidates) < sum(stratum["target"] for stratum in pool["strata"]):
        raise ValueError(f"only {len(candidates)} candidates; the declared cohort is too large")
    cohort, selected = build_cohort(candidates, pool)
    return write_pool(selected["selected"], cohort, pool, excluded, raw_path)


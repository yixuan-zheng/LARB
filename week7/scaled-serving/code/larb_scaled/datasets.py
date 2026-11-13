"""Dataset normalization, exclusion rules and deterministic cohort selection."""
import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import config

INSTRUCTION = "\nPlease put your final answer within \\boxed{}."
DIAGRAM_RE = re.compile(r"(tikzpicture|includegraphics|begin\{asy\}|\\asy\b|\[asy\]|!\[)", re.I)
PROOF_RE = re.compile(r"(prove that|proof|show that|construct a)", re.I)
MC_RE = re.compile(r"(which of the following|select all that apply)", re.I)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalise_space(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def parse_problem_type(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = ast.literal_eval(str(value))
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (ValueError, SyntaxError):
        pass
    return [str(value)]


def prompt_for(problem):
    return normalise_space(problem) + INSTRUCTION


def normalise_entry(role, entry, raw_rows):
    rows = []
    for index, row in enumerate(raw_rows, start=1):
        qid = row.get("problem_idx", row.get("id", row.get("problem_id", index)))
        try:
            qid_int = int(qid)
        except (TypeError, ValueError):
            qid_int = index
        question_id = f"{entry['slug']}-{qid_int:03d}"
        problem = normalise_space(row.get("problem", ""))
        answer = row.get("answer", row.get("solution", ""))
        if answer is None:
            answer = ""
        answer = str(answer).strip()
        prompt = prompt_for(problem) if problem else ""
        rows.append({
            "question_id": question_id,
            "role": role,
            "pool": entry["id"],
            "pool_slug": entry["slug"],
            "source_row": qid_int,
            "source_revision": entry.get("revision"),
            "exposure": entry.get("exposure"),
            "declared_answer_type": entry.get("answer_type"),
            "answer_type": "integer" if re.fullmatch(r"-?\d+", answer) else "expression",
            "problem_type": parse_problem_type(row.get("problem_type")),
            "problem": problem,
            "answer": answer,
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else None,
            "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
            "raw_keys": sorted(row),
        })
    return rows


def exclusion_reason(question, prompt_tokens=None):
    if not question["problem"]:
        return "missing_problem"
    if not question["answer"]:
        return "missing_answer"
    if PROOF_RE.search(question["problem"]):
        return "proof_like"
    if DIAGRAM_RE.search(question["problem"]):
        return "diagram_dependent"
    if MC_RE.search(question["problem"]):
        return "multiple_choice"
    if prompt_tokens is not None and prompt_tokens > 3900:
        return "prompt_too_long"
    if len(question["answer"]) > 160:
        return "answer_too_long_for_budget"
    return None


def load_raw(entry):
    path = config.DATA_DIR / "raw" / entry["slug"] / "rows.json"
    payload = json.loads(path.read_text())
    return payload["rows"]


def apply_entry_filter(entry, rows):
    spec = entry.get("filter") or {}
    level_max = spec.get("level_max")
    row_index_min = spec.get("row_index_min", 0)
    selected = []
    for index, row in enumerate(rows):
        if index < row_index_min:
            continue
        if level_max is not None:
            try:
                if int(row.get("level", 0)) > int(level_max):
                    continue
            except (TypeError, ValueError):
                continue
        selected.append(row)
    return selected


def rebuild_raw_manifest():
    metas = []
    for path in sorted((config.DATA_DIR / "raw").glob("*/meta.json")):
        metas.append(json.loads(path.read_text()))
    previous = {}
    manifest_path = config.DATA_DIR / "raw/manifest.json"
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            previous = {}
    manifest = {"fetched_at": utc_now(), "datasets": metas,
                "failures": previous.get("failures", [])}
    config.write_json(manifest_path, manifest)
    return manifest


def build_all_questions():
    cfg = config.load_datasets()
    raw_manifest = rebuild_raw_manifest()
    revisions = {item["dataset"]: item.get("revision") for item in raw_manifest.get("datasets", [])}
    questions = []
    for role in ("main", "bridge", "screen", "filler"):
        for entry in cfg.get(role, []):
            entry = dict(entry, revision=revisions.get(entry["id"]))
            rows = apply_entry_filter(entry, load_raw(entry))
            questions.extend(normalise_entry(role, entry, rows))
    return questions


def mark_exclusions(questions, prompt_token_counts=None):
    prompt_token_counts = prompt_token_counts or {}
    seen = {}
    excluded = []
    kept = []
    for question in questions:
        reason = exclusion_reason(question, prompt_token_counts.get(question["question_id"]))
        # The AIME 2025 bridge must keep all 30 items to compare with the saved
        # 30-question screen. Flags are recorded but do not exclude bridge items
        # unless the text or answer is missing.
        bridge_flag = reason if question["role"] == "bridge" else None
        if question["role"] == "bridge" and reason not in ("missing_problem", "missing_answer"):
            reason = None
        if reason is None:
            key = normalise_space(question["problem"]).lower()
            if key in seen:
                reason = f"duplicate_of:{seen[key]}"
            else:
                seen[key] = question["question_id"]
        question["eligible"] = reason is None
        question["exclusion"] = reason
        question["bridge_flag"] = bridge_flag
        if reason:
            excluded.append({"question_id": question["question_id"], "pool": question["pool"],
                             "reason": reason})
        else:
            kept.append(question)
    return kept, excluded


def hash_rank(ids, salt):
    return sorted(ids, key=lambda qid: (hashlib.sha256(f"{salt}:{qid}".encode()).hexdigest(), qid))


def select_cohort(questions, salt="larb-scaled-v1", preview_size=24,
                  screen_aime=24, screen_hmmt=24, filler_size=200):
    eligible = [q for q in questions if q["eligible"]]
    by_role = {}
    for question in eligible:
        by_role.setdefault(question["role"], []).append(question)
    main = by_role.get("main", [])
    bridge = by_role.get("bridge", [])
    screen = by_role.get("screen", [])
    filler = by_role.get("filler", [])
    if len(main) < 200:
        raise ValueError(f"main cohort too small after exclusions: {len(main)}")
    main_ids = [q["question_id"] for q in main]
    preview_ids = hash_rank(main_ids, salt + ":preview")[:preview_size]
    preview_set = set(preview_ids)
    main_ids = [qid for qid in main_ids if qid not in preview_set]
    aime_screen = [q["question_id"] for q in screen if q["pool"].startswith("MathArena/aime_2023")]
    hmmt_screen = [q["question_id"] for q in screen if "hmmt_feb_2024" in q["pool"]]
    screen_ids = (hash_rank(aime_screen, salt + ":screen:aime")[:screen_aime] +
                  hash_rank(hmmt_screen, salt + ":screen:hmmt")[:screen_hmmt])
    bridge_ids = [q["question_id"] for q in bridge]
    filler_ids = hash_rank([q["question_id"] for q in filler], salt + ":filler")[:filler_size]
    by_id = {q["question_id"]: q for q in eligible}
    return {
        "schema_version": 1,
        "salt": salt,
        "generated_at": utc_now(),
        "counts": {
            "main_pool": len(main),
            "preview": len(preview_ids),
            "main": len(main_ids),
            "bridge": len(bridge_ids),
            "screen": len(screen_ids),
            "filler": len(filler_ids),
        },
        "main_ids": main_ids,
        "preview_ids": preview_ids,
        "bridge_ids": bridge_ids,
        "screen_ids": screen_ids,
        "filler_ids": filler_ids,
        "fresh_ids": [qid for qid in main_ids if by_id[qid]["exposure"] == "fresh"],
        "recent_ids": [qid for qid in main_ids if by_id[qid]["exposure"] == "recent"],
        "exposed_ids": [qid for qid in main_ids if by_id[qid]["exposure"] == "exposed"],
        "question_file": "data/processed/questions.jsonl",
        "note": "Question text lives once in questions.jsonl; this file stores frozen IDs and counts.",
    }


def write_questions(questions, path=None):
    path = path or (config.DATA_DIR / "processed/questions.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for question in sorted(questions, key=lambda q: (q["role"], q["question_id"])):
            handle.write(json.dumps(question, ensure_ascii=False) + "\n")
    return path


def validate_questions(questions):
    required = {"question_id", "role", "pool", "problem", "answer", "prompt", "prompt_sha256",
                "exposure", "answer_type", "eligible", "exclusion"}
    ids = set()
    for question in questions:
        missing = required - set(question)
        if missing:
            raise ValueError(f"{question.get('question_id')} missing {sorted(missing)}")
        if question["question_id"] in ids:
            raise ValueError(f"duplicate question id {question['question_id']}")
        ids.add(question["question_id"])
        if question["eligible"]:
            if not question["problem"] or not question["answer"]:
                raise ValueError(f"eligible question lacks text/answer: {question['question_id']}")
            if hashlib.sha256(question["prompt"].encode()).hexdigest() != question["prompt_sha256"]:
                raise ValueError(f"prompt hash mismatch: {question['question_id']}")
    return True


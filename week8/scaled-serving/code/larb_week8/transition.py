"""CPU-side transition check for the Week 8 GPU qualification job.

This is deliberately paranoid: it verifies the frozen week 7 source lock, the
new pool/cohort/trace hashes, the real context limit, the preview/main
disjointness, the grading rule, the dry-run phase counts and the sbatch syntax.
A failure here is cheaper than a failed GPU allocation.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import Counter
from pathlib import Path

from larb_week8 import audit, config
from larb_week8.questions import load_merged_questions
from larb_scaled import workload


def _check(name: str, ok: bool, detail=None) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _load_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def check_source_lock() -> dict:
    try:
        result = config.verify_week7_source_lock()
        return _check("week7_source_lock", True, result)
    except Exception as exc:
        return _check("week7_source_lock", False, repr(exc))


def check_pool() -> list[dict]:
    checks = []
    pool = config.load_pool()
    raw = config.DATA_DIR / "raw" / pool["slug"] / pool["source_file"]
    checks.append(_check("raw_source_exists", raw.exists(), str(raw)))
    if raw.exists():
        checks.append(_check("raw_source_hash", config.digest(raw) == pool["source_sha256"],
                             config.digest(raw)))
    questions = config.load_questions()
    cohort = config.load_cohort()
    checks.append(_check("question_count", len(questions) == 240, len(questions)))
    checks.append(_check("question_ids_unique", len(set(questions)) == len(questions)))
    bad = []
    for qid, question in questions.items():
        if not question.get("eligible"):
            bad.append((qid, "not_eligible"))
        if not question.get("answer"):
            bad.append((qid, "missing_answer"))
        if question.get("prompt_sha256") != hashlib.sha256(
                question["prompt"].encode("utf-8")).hexdigest():
            bad.append((qid, "prompt_hash"))
        if (question.get("prompt_tokens") or 0) > pool["filters"]["prompt_max_tokens"]:
            bad.append((qid, "prompt_tokens"))
    checks.append(_check("question_records", not bad, bad[:10]))
    counts = cohort["counts"]
    checks.append(_check("cohort_counts",
                         counts["selected"] == 240 and counts["main"] == 216
                         and counts["preview"] == 24 and counts["preview48"] == 48
                         and counts["main_after_preview48"] == 192
                         and counts["calibration"] == 48 and counts["filler"] == 92,
                         counts))
    checks.append(_check("preview_main_disjoint",
                         not (set(cohort["preview_ids"]) & set(cohort["main_ids"])),
                         None))
    checks.append(_check("calibration_subset_main",
                         set(cohort["calibration_ids"]) <= set(cohort["main_after_preview48_ids"]),
                         None))
    checks.append(_check("filler_ids_present",
                         all(qid in config.load_week7_questions() for qid in cohort["filler_ids"]),
                         None))
    return checks


def check_traces() -> list[dict]:
    checks = []
    cohort = config.load_cohort()
    from larb_week8.questions import load_merged_questions
    questions = load_merged_questions()
    protocol = config.load_protocol()
    specs = [
        ("gate-omni-preview.jsonl", "gate-omni-preview", 24, cohort["preview_ids"]),
        ("gate-omni-preview48.jsonl", "gate-omni-preview48", 48, cohort["preview48_ids"]),
    ]
    for rate in config.load_qualify()["calibration"]["candidate_rates_per_hour"]:
        name = f"gate-omni-cal-{int(rate)}"
        specs.append((f"{name}.jsonl", name, None, cohort["calibration_ids"]))
    manifest_path = config.TRACE_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"traces": {}}
    for filename, condition, expected, allowed in specs:
        path = config.TRACE_DIR / filename
        if not path.exists():
            checks.append(_check(f"trace:{filename}", False, "missing"))
            continue
        rows = _load_trace(path)
        try:
            workload.validate_trace(rows, condition, protocol, cohort, questions,
                                    allowed_signal_ids=allowed)
            checks.append(_check(f"trace_valid:{filename}", True, len(rows)))
        except Exception as exc:
            checks.append(_check(f"trace_valid:{filename}", False, repr(exc)))
        if expected is not None:
            checks.append(_check(f"trace_rows:{filename}", len(rows) == expected, len(rows)))
        entry = manifest.get("traces", {}).get(condition)
        if entry:
            checks.append(_check(f"trace_hash:{filename}",
                                 config.digest(path) == entry.get("sha256"),
                                 config.digest(path)))
    return checks


def check_context(max_items: int | None = None) -> dict:
    try:
        from transformers import AutoTokenizer
    except Exception as exc:
        return _check("exact_context", False, f"transformers unavailable: {exc}")
    model = os.environ.get("LARB_MODEL_PATH",
                           config.load_protocol()["model"]["local_path_default"])
    try:
        tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    except Exception as exc:
        return _check("exact_context", False, f"tokenizer load failed: {exc}")
    content = load_merged_questions()
    items = list(content.items())[:max_items] if max_items else list(content.items())
    protocol = config.load_protocol()
    cue_len = len(tokenizer.encode(
        protocol["answer_contracts"]["legacy"]["cue"], add_special_tokens=False))
    max_tokens = (protocol["budgets"]["long"] + cue_len
                  + protocol["answer_contracts"]["legacy"]["answer_cap"] + 2)
    max_prompt = 0
    max_id = None
    margins = []
    over = []
    for qid, question in items:
        rendered = tokenizer.apply_chat_template(
            [{"role": "user", "content": question["prompt"]}],
            tokenize=False, add_generation_prompt=True, enable_thinking=True)
        count = len(tokenizer.encode(rendered, add_special_tokens=False))
        if count > max_prompt:
            max_prompt, max_id = count, qid
        margin = config.load_protocol()["engine"]["max_model_len"] - (count + max_tokens)
        margins.append(margin)
        if margin < 0:
            over.append((qid, count))
    return _check("exact_context", not over,
                  {"checked": len(items), "max_prompt_tokens": max_prompt,
                   "max_id": max_id, "min_margin": min(margins) if margins else None,
                   "over": over[:5], "max_tokens": max_tokens, "cue_tokens": cue_len})



def check_grading() -> list[dict]:
    checks = []
    try:
        import math_verify  # noqa: F401
        checks.append(_check("math_verify_import", True, math_verify.__file__))
    except Exception as exc:
        checks.append(_check("math_verify_import", False, repr(exc)))
        return checks
    checks.append(_check(
        "math_verify_false_positive_guard",
        not audit.safe_math_verify_match("3-2\\sqrt{2}",
                                         "3+\\sqrt{2}+\\sqrt{3}+\\sqrt{6}"),
        "safe rule rejects the known lossy parse"))
    checks.append(_check(
        "dfrac_normalisation",
        audit.safe_math_verify_match(audit.normalise_math("\\frac{5}{3}"),
                                     audit.normalise_math("\\dfrac{5}{3}")),
        "dfrac and frac compare equal after normalisation"))
    return checks


def check_configs() -> list[dict]:
    checks = []
    draft = config.load_p2_draft()
    checks.append(_check("p2_draft_withheld",
                         draft.get("p2_authorised") is False
                         and "withheld" in draft.get("status", ""),
                         draft.get("status")))
    checks.append(_check("p2_draft_deadline", draft.get("deadline_seconds") == 240,
                         draft.get("deadline_seconds")))
    checks.append(_check("p2_draft_rate_empty", draft.get("arrival_rate_per_hour") is None,
                         draft.get("arrival_rate_per_hour")))
    qualify = config.load_qualify()
    checks.append(_check("qualify_slo_240", qualify["slo"]["deadline_seconds"] == 240,
                         qualify["slo"]["deadline_seconds"]))
    checks.append(_check("qualify_deadline_consistency",
                         qualify["slo"]["deadline_seconds"]
                         == qualify["calibration"]["deadline_seconds"]
                         == qualify["p2"]["deadline_seconds"],
                         {"slo": qualify["slo"]["deadline_seconds"],
                          "calibration": qualify["calibration"]["deadline_seconds"],
                          "p2": qualify["p2"]["deadline_seconds"]}))
    checks.append(_check("qualify_preview_and",
                         qualify["preview"]["pass"].get("all_criteria") == "AND",
                         qualify["preview"]["pass"].get("all_criteria")))
    checks.append(_check("no_frozen_p2_before_qualification",
                         not config.P2_FROZEN_CONFIG.exists(),
                         str(config.P2_FROZEN_CONFIG)))
    return checks


def check_sbatch() -> list[dict]:
    checks = []
    for path in sorted((config.WEEK8_ROOT / "sbatch").glob("*.sbatch")):
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        checks.append(_check(f"sbatch:{path.name}", result.returncode == 0,
                             result.stderr.strip()))
    return checks


def check_dry_run() -> list[dict]:
    from larb_week8 import runner
    checks = []
    preview24 = runner.plan_preview(24)
    preview48 = runner.plan_preview(48)
    rates = config.load_qualify()["calibration"]["candidate_rates_per_hour"]
    calibration = runner.plan_calibration(rates, 25.0)
    checks.append(_check("dry_preview24",
                         len(preview24) == 3 and sum(p["request_count"] for p in preview24) == 72,
                         {"phases": len(preview24),
                          "requests": sum(p["request_count"] for p in preview24)}))
    checks.append(_check("dry_preview48",
                         len(preview48) == 3 and sum(p["request_count"] for p in preview48) == 144,
                         {"phases": len(preview48),
                          "requests": sum(p["request_count"] for p in preview48)}))
    checks.append(_check("dry_calibration",
                         len(calibration) == len(rates)
                         and sum(p["request_count"] for p in calibration) > 3000,
                         {"phases": len(calibration),
                          "requests": sum(p["request_count"] for p in calibration)}))
    return checks



def write_source_lock() -> dict:
    lock = {
        "created_at": config.utc_now(),
        "stage": "P2A-pre-run",
        "pool": config.load_pool()["name"],
        "week7_source_lock": config.verify_week7_source_lock(),
        "week8_code": config.code_hashes(),
        "configs": config.config_hashes(),
        "artifacts": config.artifact_hashes(),
        "model": config.load_protocol()["model"],
        "engine": config.load_protocol()["engine"],
        "slo_seconds": config.load_qualify()["slo"]["deadline_seconds"],
        "preview_pass_rule": config.load_qualify()["preview"]["pass"],
        "calibration_rates": config.load_qualify()["calibration"]["candidate_rates_per_hour"],
        "p2_authorised": False,
    }
    config.write_json(config.SOURCE_LOCK_PATH, lock)
    return lock


def run(max_items: int | None = None, write_lock: bool = True,
        skip_context: bool = False, skip_grading: bool = False,
        out: Path | None = None) -> dict:
    checks = []
    checks.append(check_source_lock())
    checks.extend(check_pool())
    checks.extend(check_traces())
    if skip_context:
        checks.append({"name": "exact_context", "ok": True, "skipped": True,
                       "detail": "skipped in this environment"})
    else:
        checks.append(check_context(max_items=max_items))
    if skip_grading:
        checks.append({"name": "math_verify_import", "ok": True, "skipped": True,
                       "detail": "skipped in this environment"})
        checks.append({"name": "grading_rule", "ok": True, "skipped": True,
                       "detail": "skipped in this environment"})
    else:
        checks.extend(check_grading())
    checks.extend(check_configs())
    checks.extend(check_sbatch())
    checks.extend(check_dry_run())
    failed = [check for check in checks if not check["ok"]]
    result = {
        "generated_at": config.utc_now(),
        "checks": checks,
        "failures": failed,
        "ok": not failed,
        "counts": {"checks": len(checks), "failed": len(failed)},
    }
    out = Path(out or (config.RESULTS_DIR / "transition-check.json"))
    config.write_json(out, result)
    if write_lock:
        result["source_lock"] = write_source_lock()
    print(json.dumps({"ok": result["ok"], "checks": len(checks),
                      "failed": [check["name"] for check in failed],
                      "skipped": [check["name"] for check in checks if check.get("skipped")],
                      "source_lock": str(config.SOURCE_LOCK_PATH)}, indent=2))
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-context-items", type=int,
                        help="limit the exact tokenizer check (default: all 240)")
    parser.add_argument("--skip-context", action="store_true")
    parser.add_argument("--skip-grading", action="store_true")
    parser.add_argument("--no-lock", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = run(args.max_context_items, write_lock=not args.no_lock,
                 skip_context=args.skip_context, skip_grading=args.skip_grading,
                 out=args.out)
    raise SystemExit(0 if result["ok"] else 1)



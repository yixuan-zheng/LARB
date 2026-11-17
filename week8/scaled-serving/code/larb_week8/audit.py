"""CPU audit of the P1 slope records, per pool and under a normalised grader.

The P1 aggregate hides two things this audit makes explicit:

* the 2023 AIME half of the screen is a clean integer-answer set, while the
  HMMT 2024 half contains LaTeX forms that the frozen ``math_verify`` build
  cannot parse (notably ``\\dfrac``);
* the screen summary uses an OR between the gain and answer-change criteria,
  while the pre-registered pool rule is an AND.

No model call is made.  Run with the analysis venv, which has ``math_verify``.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from numbers import Integral
from pathlib import Path

from larb_week8 import config
from larb_scaled import analysis, grading, stats

SLOPE_DIR = config.WEEK7_ROOT / "results/p1/runs/slope/requests"
WEEK7_QUESTIONS = config.WEEK7_QUESTIONS_PATH
WEEK7_TOKEN_COUNTS = config.WEEK7_ROOT / "data/processed/prompt-token-counts.json"


def normalise_math(value):
    if value is None:
        return None
    text = str(value)
    text = text.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    text = text.replace("\\left", "").replace("\\right", "")
    text = text.replace("\\!", "").replace("\\,", "").replace("\\;", "")
    text = text.replace("\\ ", "").replace("$", "")
    text = re.sub(r"\s+", "", text)
    return text


def _parse(expr):
    try:
        from math_verify import parse
        return parse(expr)
    except Exception:
        return []


def _parse_is_faithful(expr: str) -> bool:
    """Reject Math-Verify parses that silently kept only a leading integer.

    The installed Math-Verify 0.9.0 parses ``3 - 2*sqrt(2)`` and
    ``3 + sqrt(2) + sqrt(3) + sqrt(6)`` both as ``[3, '3']``.  Treating those
    as equal is a false positive, so an integer parse of an expression that
    contains a non-integer operator is marked unreliable.
    """
    parsed = _parse(expr)
    if not parsed:
        return False
    value = parsed[0]
    text = normalise_math(expr) or ""
    integer_like = isinstance(value, Integral) or bool(getattr(value, "is_Integer", False))
    if integer_like and re.search(r"\\sqrt|\\frac|/|\^|\\pi|\\cdot|\\times|\\pm", text):
        return False
    return True


def safe_math_verify_match(extracted, reference) -> bool:
    if extracted is None or reference is None:
        return False
    if not (_parse_is_faithful(extracted) and _parse_is_faithful(reference)):
        return False
    return bool(grading.math_verify_match(extracted, reference))


def grade_record(raw: dict, mode: str = "normalized") -> dict:
    reference = raw.get("reference")
    raw_output = raw.get("raw_output", "")
    completion = analysis.audit_completion(raw, raw.get("cue_start"))
    extraction = grading.extract_boxed(raw_output)
    extracted = extraction["value"]
    if mode == "raw":
        result = grading.grade(raw_output, reference, use_math_verify=True)
        match = result["match"]
        correct_answer = result["correct"]
    elif mode == "normalized_exact":
        a = normalise_math(extracted)
        b = normalise_math(reference)
        if a is not None and b is not None and a == b:
            match, correct_answer = "normalized_exact", True
        elif a is None:
            match, correct_answer = "missing", False
        else:
            match, correct_answer = "mismatch", False
    elif mode == "normalized_safe":
        a = normalise_math(extracted)
        b = normalise_math(reference)
        if a is not None and b is not None and a == b:
            match, correct_answer = "normalized_exact", True
        elif safe_math_verify_match(a, b):
            match, correct_answer = "normalized_safe_math_verify", True
        elif a is None:
            match, correct_answer = "missing", False
        else:
            match, correct_answer = "mismatch", False
    elif mode == "normalized":
        a = normalise_math(extracted)
        b = normalise_math(reference)
        if a is not None and b is not None and a == b:
            match, correct_answer = "normalized_exact", True
        elif a is not None and b is not None and grading.math_verify_match(a, b):
            match, correct_answer = "normalized_math_verify", True
        elif a is None:
            match, correct_answer = "missing", False
        else:
            match, correct_answer = "mismatch", False
    else:
        raise ValueError(mode)
    return {
        "correct": bool(completion["normal"] and correct_answer),
        "normal": completion["normal"],
        "reason": completion["reason"],
        "thinking_tokens": completion["thinking_tokens"],
        "answer_tokens": completion["answer_tokens"],
        "extracted": extracted,
        "normalised_extracted": normalise_math(extracted),
        "match": match,
        "issue": extraction["issue"],
        "complete": completion["complete"],
    }


def load_records() -> list[dict]:
    records = []
    for path in sorted(SLOPE_DIR.glob("*.json")):
        records.append(json.loads(path.read_text()))
    if not records:
        raise FileNotFoundError(f"no P1 slope records under {SLOPE_DIR}")
    return records


def load_questions() -> dict[str, dict]:
    rows = {}
    with WEEK7_QUESTIONS.open() as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows[row["question_id"]] = row
    return rows


def load_token_counts() -> dict[str, int]:
    return json.loads(WEEK7_TOKEN_COUNTS.read_text())


def wilson(correct: int, n: int):
    low, high = stats.wilson_interval(correct, n)
    return {"low": low, "high": high}


def summarise_arm(records: list[dict], mode: str) -> dict:
    graded = [grade_record(raw, mode) for raw in records]
    n = len(graded)
    correct = sum(item["correct"] for item in graded)
    caps = sum(item["reason"] == "answer_cap" for item in graded)
    missing = sum(item["issue"] == "missing_complete_box" for item in graded)
    thinking = [item["thinking_tokens"] for item in graded if item["thinking_tokens"]]
    return {
        "n": n,
        "correct": correct,
        "accuracy": correct / n if n else None,
        "wilson": wilson(correct, n),
        "cap_rate": caps / n if n else None,
        "missing_box_rate": missing / n if n else None,
        "thinking_tokens_median": statistics.median(thinking) if thinking else None,
        "match_counts": dict(Counter(item["match"] for item in graded)),
    }


def paired_summary(records: list[dict], arm_a: str, arm_b: str, mode: str,
                   pool_filter=None) -> dict:
    selected = [raw for raw in records if pool_filter is None or pool_filter(raw["source"])]
    by_identity = {}
    for raw in selected:
        by_identity.setdefault((raw["question_id"], raw["seed"]), {})[raw["arm"]] = raw
    pairs = []
    for identity, arms in sorted(by_identity.items()):
        if arm_a not in arms or arm_b not in arms:
            continue
        a = grade_record(arms[arm_a], mode)
        b = grade_record(arms[arm_b], mode)
        pairs.append({"question_id": identity[0], "seed": identity[1],
                      "a": int(a["correct"]), "b": int(b["correct"]),
                      "a_extracted": a["normalised_extracted"],
                      "b_extracted": b["normalised_extracted"]})
    if not pairs:
        return {"n": 0}
    both = sum(1 for p in pairs if p["a"] and p["b"])
    neither = sum(1 for p in pairs if not p["a"] and not p["b"])
    a_only = sum(1 for p in pairs if p["a"] and not p["b"])
    b_only = sum(1 for p in pairs if not p["a"] and p["b"])
    discordance = (a_only + b_only) / len(pairs)
    changes = sum(1 for p in pairs if p["a_extracted"] != p["b_extracted"])
    nonmissing = sum(1 for p in pairs
                     if p["a_extracted"] is not None and p["b_extracted"] is not None
                     and p["a_extracted"] != p["b_extracted"])
    comparable = sum(1 for p in pairs
                     if p["a_extracted"] is not None and p["b_extracted"] is not None)
    return {
        "n": len(pairs),
        "both": both,
        "neither": neither,
        "a_only": a_only,
        "b_only": b_only,
        "discordance": discordance,
        "gain": (sum(p["b"] for p in pairs) - sum(p["a"] for p in pairs)) / len(pairs),
        "answer_change_fraction": changes / len(pairs),
        "answer_change_fraction_nonmissing": (nonmissing / comparable if comparable else None),
        "sign_test": stats.sign_test([p["a"] - p["b"] for p in pairs]),
    }


def prompt_checks(records: list[dict]) -> dict:
    questions = load_questions()
    token_counts = load_token_counts()
    issues = []
    checked = 0
    for raw in records:
        qid = raw["question_id"]
        question = questions.get(qid)
        if question is None:
            issues.append({"question_id": qid, "issue": "unknown_question"})
            continue
        checked += 1
        prompt = raw.get("prompt", "")
        if raw.get("reference") != question["answer"]:
            issues.append({"question_id": qid, "issue": "reference_mismatch"})
        if question["prompt"] not in prompt:
            issues.append({"question_id": qid, "issue": "question_text_not_verbatim"})
        if not prompt.startswith("<|im_start|>user\n"):
            issues.append({"question_id": qid, "issue": "missing_user_prefix"})
        if not prompt.endswith("<|im_start|>assistant\n"):
            issues.append({"question_id": qid, "issue": "missing_assistant_suffix"})
        expected = token_counts.get(qid)
        actual = len(raw.get("prompt_token_ids") or [])
        if expected is not None and abs(actual - expected) > 40:
            issues.append({"question_id": qid, "issue": "token_count_drift",
                           "expected_plus32": expected, "actual": actual})
    return {"checked": checked,
            "issue_count": len(issues),
            "issues": issues[:50],
            "issue_types": dict(Counter(item["issue"] for item in issues))}


def power_table() -> list[dict]:
    rows = []
    for questions in (24, 25, 48, 192, 216):
        for seeds in (1, 4):
            for icc in (0.2, 0.4, 0.6):
                n_eff = stats.effective_n(questions, seeds, icc)
                rows.append({"questions": questions, "seeds": seeds, "icc": icc,
                             "effective_pairs": n_eff,
                             "mde_points_disc20": 100 * stats.paired_mde(n_eff, 0.20),
                             "mde_points_disc30": 100 * stats.paired_mde(n_eff, 0.30)})
    return rows



def analyse() -> dict:
    records = load_records()
    result = {
        "generated_at": config.utc_now(),
        "source_dir": str(SLOPE_DIR),
        "record_count": len(records),
        "conditions": dict(Counter(raw["condition"] for raw in records)),
        "arms": dict(Counter(raw["arm"] for raw in records)),
        "summaries": {},
        "paired": {},
        "grading_flips": {},
        "prompt_checks": {},
        "pass_rules": {},
        "power": power_table(),
        "notes": [
            "normalized grading maps \\dfrac to \\frac and strips \\left/\\right before exact and Math-Verify comparison.",
            "The pre-registered slope rule is gain >= 8 points AND answer change >= 10% AND 8k accuracy in [0.35,0.75] AND 8k cap <= 20%.",
            "The P1 summariser used OR between gain and answer change; both rules are reported.",
        ],
    }
    for condition in ("gate-screen", "gate-preview"):
        condition_records = [raw for raw in records if raw["condition"] == condition]
        if not condition_records:
            continue
        result["summaries"][condition] = {}
        pool_labels = ({"screen_all": lambda source: True,
                        "screen_aime2023": lambda source: "aime_2023" in source,
                        "screen_hmmt2024": lambda source: "hmmt_feb_2024" in source}
                       if condition == "gate-screen" else
                       {"preview_all": lambda source: True})
        for pool_name, pool_filter in pool_labels.items():
            pool_records = [raw for raw in condition_records if pool_filter(raw["source"])]
            if not pool_records:
                continue
            result["summaries"][condition][pool_name] = {}
            for mode in ("raw", "normalized_exact", "normalized_safe", "normalized"):
                result["summaries"][condition][pool_name][mode] = {
                    arm: summarise_arm([raw for raw in pool_records if raw["arm"] == arm], mode)
                    for arm in ("fixed4k", "fixed6k", "fixed8k")
                }
            key = f"{condition}:{pool_name}"
            result["paired"][key] = {
                "fixed4k_vs_fixed8k": paired_summary(pool_records, "fixed4k", "fixed8k",
                                                     "normalized_safe", pool_filter),
                "fixed4k_vs_fixed6k": paired_summary(pool_records, "fixed4k", "fixed6k",
                                                     "normalized_safe", pool_filter),
                "fixed6k_vs_fixed8k": paired_summary(pool_records, "fixed6k", "fixed8k",
                                                     "normalized_safe", pool_filter),
            }
            acc = result["summaries"][condition][pool_name]["normalized_safe"]
            gain = (acc["fixed8k"]["accuracy"] - acc["fixed4k"]["accuracy"]
                    if acc["fixed8k"]["accuracy"] is not None
                    and acc["fixed4k"]["accuracy"] is not None else None)
            change = result["paired"][key]["fixed4k_vs_fixed8k"].get("answer_change_fraction")
            acc8 = acc["fixed8k"]["accuracy"]
            cap8 = acc["fixed8k"]["cap_rate"]
            think8 = acc["fixed8k"]["thinking_tokens_median"]
            and_pass = bool(gain is not None and change is not None
                            and gain >= 0.08 and change >= 0.10
                            and acc8 is not None and 0.35 <= acc8 <= 0.75
                            and (cap8 or 0) <= 0.20 and (think8 or 0) <= 8192)
            or_pass = bool(gain is not None and change is not None
                           and (gain >= 0.08 or change >= 0.10)
                           and acc8 is not None and 0.35 <= acc8 <= 0.75
                           and (cap8 or 0) <= 0.20 and (think8 or 0) <= 8192)
            result["pass_rules"][key] = {
                "gain_4k_to_8k": gain,
                "answer_change_fraction": change,
                "accuracy_8k": acc8,
                "cap_rate_8k": cap8,
                "thinking_median_8k": think8,
                "pre_registered_and": and_pass,
                "p1_summariser_or": or_pass,
            }
    # Grading flips: safe normalised grading fixes raw Math-Verify failures;
    # loose Math-Verify can also introduce false positives.
    fixes, false_positives = [], []
    for raw in records:
        raw_grade = grade_record(raw, "raw")
        safe_grade = grade_record(raw, "normalized_safe")
        exact_grade = grade_record(raw, "normalized_exact")
        loose_grade = grade_record(raw, "normalized")
        if safe_grade["correct"] and not raw_grade["correct"]:
            fixes.append({"question_id": raw["question_id"], "arm": raw["arm"],
                          "condition": raw["condition"], "source": raw["source"],
                          "reference": raw["reference"],
                          "extracted": safe_grade["extracted"],
                          "raw_match": raw_grade["match"]})
        if loose_grade["correct"] and not safe_grade["correct"] and not exact_grade["correct"]:
            false_positives.append({"question_id": raw["question_id"], "arm": raw["arm"],
                                    "condition": raw["condition"], "source": raw["source"],
                                    "reference": raw["reference"],
                                    "extracted": loose_grade["extracted"]})
    result["grading_flips"] = {
        "fixes": {"count": len(fixes),
                  "by_source": dict(Counter(item["source"] for item in fixes)),
                  "examples": fixes[:50]},
        "loose_math_verify_false_positives": {
            "count": len(false_positives),
            "by_source": dict(Counter(item["source"] for item in false_positives)),
            "examples": false_positives[:50],
        },
    }
    result["prompt_checks"] = prompt_checks(records)
    return result



def write_markdown(result: dict, path: Path) -> None:
    lines = ["# P1 slope-record audit (CPU-only)", "",
             f"Generated: {result['generated_at']}", "",
             "Source: `week7/scaled-serving/results/p1/runs/slope/requests`", "",
             "## Summary", ""]
    for key, rule in sorted(result["pass_rules"].items()):
        lines.append(f"### {key}")
        lines.append("")
        lines.append("| metric | value |")
        lines.append("|---|---:|")
        for metric, value in rule.items():
            if isinstance(value, float):
                value = f"{value:.3f}"
            lines.append(f"| {metric} | {value} |")
        lines.append("")
    lines.append("## Per-pool accuracy (safe normalised grader)")
    lines.append("")
    lines.append("| condition | pool | arm | n | correct | accuracy | 95% CI | cap rate | missing box |")
    lines.append("|---|---|---|---:|---:|---:|---|---:|---:|")
    for condition, pools in result["summaries"].items():
        for pool_name, modes in pools.items():
            for arm, summary in modes["normalized_safe"].items():
                ci = summary["wilson"]
                lines.append(
                    f"| {condition} | {pool_name} | {arm} | {summary['n']} | "
                    f"{summary['correct']} | {summary['accuracy']:.3f} | "
                    f"[{ci['low']:.3f}, {ci['high']:.3f}] | "
                    f"{summary['cap_rate']:.3f} | {summary['missing_box_rate']:.3f} |")
    lines.append("")
    lines.append("## Paired 4k vs 8k (safe normalised grader)")
    lines.append("")
    lines.append("| condition | pool | n pairs | 4k only | 8k only | neither | both | discordance | gain | answer change |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for key, comparisons in result["paired"].items():
        pair = comparisons["fixed4k_vs_fixed8k"]
        if not pair.get("n"):
            continue
        condition, pool_name = key.split(":", 1)
        lines.append(
            f"| {condition} | {pool_name} | {pair['n']} | {pair['a_only']} | {pair['b_only']} | "
            f"{pair['neither']} | {pair['both']} | {pair['discordance']:.3f} | "
            f"{pair['gain']:+.3f} | {pair['answer_change_fraction']:.3f} |")
    lines.append("")
    lines.append("## Grading-contract findings")
    lines.append("")
    lines.append(f"Raw-Math-Verify failures fixed by safe normalised grading: "
                 f"**{result['grading_flips']['fixes']['count']}**")
    lines.append("")
    lines.append(f"By source: `{result['grading_flips']['fixes']['by_source']}`")
    lines.append("")
    lines.append(f"Loose-Math-Verify false positives rejected by safe grading: "
                 f"**{result['grading_flips']['loose_math_verify_false_positives']['count']}**")
    lines.append("")
    lines.append(f"By source: `{result['grading_flips']['loose_math_verify_false_positives']['by_source']}`")
    lines.append("")
    lines.append("## Prompt checks")
    lines.append("")
    lines.append(f"Checked records: {result['prompt_checks']['checked']}; issues: {result['prompt_checks']['issue_count']}")
    lines.append("")
    if result["prompt_checks"]["issue_types"]:
        lines.append(f"Issue types: `{result['prompt_checks']['issue_types']}`")
        lines.append("")
    lines.append("## Power")
    lines.append("")
    lines.append("| questions | seeds | ICC | effective pairs | MDE @20% | MDE @30% |")
    lines.append("|---:|---:|---:|---:|---:|---:|")
    for row in result["power"]:
        if row["questions"] in (24, 25, 48, 192, 216):
            lines.append(f"| {row['questions']} | {row['seeds']} | {row['icc']} | "
                         f"{row['effective_pairs']:.0f} | {row['mde_points_disc20']:.1f} | "
                         f"{row['mde_points_disc30']:.1f} |")
    lines.append("")
    Path(path).write_text("\n".join(lines) + "\n")


def main(out: Path | None = None, report: Path | None = None) -> dict:
    result = analyse()
    out = Path(out or (config.RESULTS_DIR / "p1-screen-audit.json"))
    report = Path(report or (config.REPORTS_DIR / "P1-SCREEN-AUDIT.md"))
    config.write_json(out, result)
    write_markdown(result, report)
    print(json.dumps({
        "out": str(out),
        "report": str(report),
        "pass_rules": result["pass_rules"],
        "grading_fixes": result["grading_flips"]["fixes"]["count"],
        "math_verify_false_positives": result["grading_flips"]["loose_math_verify_false_positives"]["count"],
        "prompt_issue_count": result["prompt_checks"]["issue_count"],
    }, indent=2))
    return result


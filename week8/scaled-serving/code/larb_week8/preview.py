"""Analyse the Week 8 preview and apply the pre-registered pool rule."""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from larb_week8 import audit, config
from larb_week8.questions import load_week8_questions
from larb_scaled import analysis, stats

ARMS = ("fixed4k", "fixed6k", "fixed8k")


def load_phases(run_dir: Path) -> list[dict]:
    run_dir = Path(run_dir)
    path = run_dir / "phases.json"
    if path.exists():
        phases = json.loads(path.read_text())
        if phases:
            return phases
    return [json.loads(item.read_text()) for item in sorted((run_dir / "phases").glob("*.json"))]


def load_trace(path: Path) -> list[dict]:
    rows = []
    with Path(path).open() as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def build_arm_rows(phase: dict, requests: dict[str, dict],
                   questions: dict[str, dict]) -> list[dict]:
    rows = []
    for trace in load_trace(Path(phase["trace_file"])):
        key = analysis.runtime_key(phase["condition"], phase["arm"], trace)
        raw = requests.get(key)
        grade = audit.grade_record(raw, "normalized_safe") if raw else {
            "correct": False, "normal": False, "reason": "missing",
            "thinking_tokens": 0, "answer_tokens": 0, "extracted": None,
            "normalised_extracted": None, "match": "missing", "issue": "missing",
        }
        question = questions.get(trace["question_id"], {})
        rows.append({
            "phase": phase["name"], "condition": phase["condition"],
            "arm": phase["arm"], "key": key, "present": raw is not None,
            "question_id": trace["question_id"], "seed": trace["seed"],
            "stratum": question.get("stratum"), "source": trace.get("source"),
            "difficulty": question.get("difficulty"),
            "correct": bool(grade["correct"]),
            "normal": bool(grade["normal"]),
            "reason": grade["reason"],
            "thinking_tokens": grade["thinking_tokens"],
            "answer_tokens": grade["answer_tokens"],
            "extracted": grade["normalised_extracted"],
            "match": grade["match"],
            "issue": grade["issue"],
        })
    return rows


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    present = sum(1 for row in rows if row["present"])
    correct = sum(1 for row in rows if row["correct"])
    caps = sum(1 for row in rows if row["reason"] == "answer_cap")
    missing_box = sum(1 for row in rows if row["issue"] == "missing_complete_box")
    thinking = [row["thinking_tokens"] for row in rows if row["thinking_tokens"]]
    low, high = stats.wilson_interval(correct, n)
    return {
        "planned": n, "present": present, "missing": n - present,
        "correct": correct, "accuracy": correct / n if n else None,
        "wilson": {"low": low, "high": high},
        "cap_rate": caps / n if n else None,
        "missing_box_rate": missing_box / n if n else None,
        "thinking_tokens_median": statistics.median(thinking) if thinking else None,
        "match_counts": dict(Counter(row["match"] for row in rows)),
    }


def paired(rows: list[dict]) -> dict:
    by_question = defaultdict(dict)
    for row in rows:
        by_question[row["question_id"]][row["arm"]] = row
    pairs = []
    for qid, arms in sorted(by_question.items()):
        if "fixed4k" not in arms or "fixed8k" not in arms:
            continue
        a, b = arms["fixed4k"], arms["fixed8k"]
        pairs.append({
            "question_id": qid,
            "stratum": a["stratum"],
            "a": int(a["correct"]), "b": int(b["correct"]),
            "a_extracted": a["extracted"], "b_extracted": b["extracted"],
        })
    if not pairs:
        return {"n": 0}
    both = sum(1 for p in pairs if p["a"] and p["b"])
    neither = sum(1 for p in pairs if not p["a"] and not p["b"])
    a_only = sum(1 for p in pairs if p["a"] and not p["b"])
    b_only = sum(1 for p in pairs if not p["a"] and p["b"])
    changes = sum(1 for p in pairs if p["a_extracted"] != p["b_extracted"])
    comparable = sum(1 for p in pairs
                     if p["a_extracted"] is not None and p["b_extracted"] is not None)
    nonmissing = sum(1 for p in pairs
                     if p["a_extracted"] is not None and p["b_extracted"] is not None
                     and p["a_extracted"] != p["b_extracted"])
    by_stratum = {}
    for stratum in sorted({p["stratum"] for p in pairs if p["stratum"]}):
        subset = [p for p in pairs if p["stratum"] == stratum]
        by_stratum[stratum] = {
            "n": len(subset),
            "accuracy_4k": sum(p["a"] for p in subset) / len(subset),
            "accuracy_8k": sum(p["b"] for p in subset) / len(subset),
        }
    return {
        "n": len(pairs), "both": both, "neither": neither,
        "a_only": a_only, "b_only": b_only,
        "discordance": (a_only + b_only) / len(pairs),
        "gain": (sum(p["b"] for p in pairs) - sum(p["a"] for p in pairs)) / len(pairs),
        "answer_change_fraction": changes / len(pairs),
        "answer_change_fraction_nonmissing": (nonmissing / comparable if comparable else None),
        "sign_test": stats.sign_test([p["a"] - p["b"] for p in pairs]),
        "by_stratum": by_stratum,
    }



def decide(summary: dict, pair: dict) -> dict:
    rule = config.load_qualify()["preview"]
    acc8 = summary["fixed8k"]["accuracy"]
    cap8 = summary["fixed8k"]["cap_rate"]
    think8 = summary["fixed8k"]["thinking_tokens_median"]
    gain = pair.get("gain")
    change = pair.get("answer_change_fraction")
    coverage_ok = all(summary[arm]["present"] == summary[arm]["planned"] for arm in ARMS)
    grader_ok = (summary["fixed8k"].get("missing_box_rate") or 0) <= 0.20
    pass_rule = rule["pass"]
    near_rule = rule["near_miss"]
    passed = bool(
        coverage_ok and grader_ok
        and gain is not None and change is not None
        and gain >= pass_rule["gain_4k_to_8k_min_points"] / 100.0
        and change >= pass_rule["answer_change_fraction_min"]
        and acc8 is not None
        and pass_rule["accuracy_8k_band"][0] <= acc8 <= pass_rule["accuracy_8k_band"][1]
        and (cap8 or 0) <= pass_rule["cap_rate_8k_max"]
        and (think8 or 0) <= pass_rule["thinking_median_8k_max"]
    )
    near_miss = bool(
        coverage_ok and grader_ok
        and gain is not None and change is not None
        and near_rule["gain_4k_to_8k_min_points"] / 100.0 <= gain < pass_rule["gain_4k_to_8k_min_points"] / 100.0
        and change >= near_rule["answer_change_fraction_min"]
        and acc8 is not None and acc8 >= near_rule["accuracy_8k_min"]
        and (cap8 or 0) <= near_rule["cap_rate_8k_max"]
    )
    if not coverage_ok:
        decision = "inconclusive_coverage"
    elif not grader_ok:
        decision = "inconclusive_grader"
    elif passed:
        decision = "pass"
    elif near_miss:
        decision = "near_miss"
    else:
        decision = "stop"
    return {
        "decision": decision,
        "coverage_ok": coverage_ok,
        "grader_ok": grader_ok,
        "gain_4k_to_8k": gain,
        "answer_change_fraction": change,
        "accuracy_8k": acc8,
        "cap_rate_8k": cap8,
        "thinking_median_8k": think8,
        "pass_rule": pass_rule,
        "near_miss_rule": near_rule,
    }


def analyse(run_dir: Path, preview_size: int = 24) -> dict:
    run_dir = Path(run_dir)
    phases = load_phases(run_dir)
    if not phases:
        raise FileNotFoundError(f"no phases under {run_dir}")
    requests = analysis.load_requests(run_dir)
    questions = load_week8_questions()
    rows = []
    for phase in phases:
        rows.extend(build_arm_rows(phase, requests, questions))
    by_arm = {arm: summarise([row for row in rows if row["arm"] == arm]) for arm in ARMS}
    pair = paired(rows)
    decision = decide(by_arm, pair)
    return {
        "generated_at": config.utc_now(),
        "run_dir": str(run_dir),
        "preview_size": preview_size,
        "phases": [phase["name"] for phase in phases],
        "request_count": len(requests),
        "arms": by_arm,
        "paired_4k_vs_8k": pair,
        "decision": decision,
        "rows": rows,
    }


def write_markdown(result: dict, path: Path) -> None:
    decision = result["decision"]
    lines = [f"# Week 8 preview ({result['preview_size']} items)", "",
             f"Generated: {result['generated_at']}", "",
             f"Run: `{result['run_dir']}`", "",
             "## Decision", "",
             f"**{decision['decision']}**", "",
             "| metric | value |", "|---|---:|"]
    for key in ("coverage_ok", "grader_ok", "gain_4k_to_8k",
                "answer_change_fraction", "accuracy_8k", "cap_rate_8k",
                "thinking_median_8k"):
        value = decision[key]
        if isinstance(value, float):
            value = f"{value:.3f}"
        lines.append(f"| {key} | {value} |")
    lines.append("")
    lines.append("## Arms (safe normalised grader)")
    lines.append("")
    lines.append("| arm | planned | present | correct | accuracy | 95% CI | cap rate | missing box |")
    lines.append("|---|---:|---:|---:|---:|---|---:|---:|")
    for arm in ARMS:
        item = result["arms"][arm]
        ci = item["wilson"]
        lines.append(f"| {arm} | {item['planned']} | {item['present']} | {item['correct']} | "
                     f"{item['accuracy']:.3f} | [{ci['low']:.3f}, {ci['high']:.3f}] | "
                     f"{item['cap_rate']:.3f} | {item['missing_box_rate']:.3f} |")
    lines.append("")
    pair = result["paired_4k_vs_8k"]
    if pair.get("n"):
        lines.append("## Paired 4k vs 8k")
        lines.append("")
        lines.append("| n | 4k only | 8k only | neither | both | discordance | gain | answer change | sign test p |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        lines.append(f"| {pair['n']} | {pair['a_only']} | {pair['b_only']} | {pair['neither']} | "
                     f"{pair['both']} | {pair['discordance']:.3f} | {pair['gain']:+.3f} | "
                     f"{pair['answer_change_fraction']:.3f} | {pair['sign_test']['p']:.4f} |")
        lines.append("")
        if pair.get("by_stratum"):
            lines.append("## Per stratum (descriptive)")
            lines.append("")
            lines.append("| stratum | n | 4k accuracy | 8k accuracy |")
            lines.append("|---|---:|---:|---:|")
            for stratum, item in pair["by_stratum"].items():
                lines.append(f"| {stratum} | {item['n']} | {item['accuracy_4k']:.3f} | "
                             f"{item['accuracy_8k']:.3f} |")
            lines.append("")
    Path(path).write_text("\n".join(lines) + "\n")


def main(run_dir: Path, out_dir: Path | None = None, preview_size: int = 24) -> dict:
    out_dir = Path(out_dir or config.RESULTS_DIR)
    result = analyse(run_dir, preview_size)
    out = out_dir / f"preview-{preview_size}.json"
    report = out_dir / f"PREVIEW-{preview_size}.md"
    config.write_json(out, result)
    write_markdown(result, report)
    print(json.dumps({"out": str(out), "report": str(report),
                      "decision": result["decision"]}, indent=2))
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--preview-size", type=int, choices=[24, 48], required=True)
    args = parser.parse_args()
    main(args.run, args.out, args.preview_size)



"""Tabulate the 4k->8k budget effect across every paired record in the rig.

Reads the frozen P1 slope/bridge runs and the Week 8 Omni preview, pairs
fixed4k with fixed8k by (condition, question, seed), grades with the safe
normalised rule and reports accuracy, conversions, derailments, a sign test and
the answer-channel statistics that separate the families.

Usage: PYTHONPATH=week8/scaled-serving/code:week7/scaled-serving/code \
         python code/tools/analyze_slope_history.py
"""
from __future__ import annotations

import glob
import json
import math
from collections import defaultdict
from pathlib import Path

from larb_week8 import REPO_ROOT, audit

RUN_GLOBS = (
    "week7/scaled-serving/results/p1/runs/slope/requests/*.json",
    "week7/scaled-serving/results/p1/runs/bridge/requests/*.json",
    "week8/scaled-serving/results/p2a/preview/requests/*.json",
)


def family(qid: str) -> str:
    if qid.startswith("aime"):
        return "AIME"
    if qid.startswith("hmmt"):
        return "HMMT"
    if qid.startswith("omni"):
        return "Omni-MATH"
    return "other"


def load() -> list[dict]:
    rows = []
    for pattern in RUN_GLOBS:
        for path in glob.glob(str(REPO_ROOT / pattern)):
            rows.append(json.loads(Path(path).read_text()))
    return rows


def pair(rows: list[dict]) -> list[dict]:
    index = {(r["condition"], r["arm"], r["question_id"], r["seed"]): r for r in rows}
    pairs = []
    for (condition, arm, qid, seed), four in index.items():
        if arm != "fixed4k":
            continue
        eight = index.get((condition, "fixed8k", qid, seed))
        if eight is None:
            continue
        a = audit.grade_record(four, "normalized_safe")
        b = audit.grade_record(eight, "normalized_safe")
        pairs.append({
            "family": family(qid), "a": a["correct"], "b": b["correct"],
            "changed": a["normalised_extracted"] != b["normalised_extracted"],
            "cap4": a["reason"] == "answer_cap", "ans4": a["answer_tokens"],
        })
    return pairs


def sign_p(conversions: int, derailments: int):
    n = conversions + derailments
    if n == 0:
        return None
    tail = sum(math.comb(n, k) for k in range(0, min(conversions, derailments) + 1))
    return min(1.0, 2 * tail / 2 ** n)


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    conversions = sum(1 for r in rows if not r["a"] and r["b"])
    derailments = sum(1 for r in rows if r["a"] and not r["b"])
    return {
        "n": n,
        "accuracy_4k": sum(r["a"] for r in rows) / n,
        "accuracy_8k": sum(r["b"] for r in rows) / n,
        "gain": (sum(r["b"] for r in rows) - sum(r["a"] for r in rows)) / n,
        "conversions": conversions,
        "derailments": derailments,
        "sign_p": sign_p(conversions, derailments),
        "answer_change": sum(r["changed"] for r in rows) / n,
        "answer_cap_4k": sum(r["cap4"] for r in rows) / n,
        "answer_tokens_4k_median": sorted(r["ans4"] for r in rows)[n // 2],
    }


def main() -> dict:
    pairs = pair(load())
    groups = defaultdict(list)
    for row in pairs:
        groups[row["family"]].append(row)
    result = {"all": summarise(pairs),
              "by_family": {name: summarise(rows) for name, rows in sorted(groups.items())}}
    result["non_aime"] = summarise([r for r in pairs if r["family"] != "AIME"])
    aime = groups["AIME"]
    result["aime_subsets"] = {
        "not_answer_capped": summarise([r for r in aime if not r["cap4"]]),
        "answer_capped": summarise([r for r in aime if r["cap4"]]),
        "answer_long": summarise([r for r in aime if r["ans4"] > 1500]),
        "answer_short": summarise([r for r in aime if r["ans4"] <= 800]),
    }
    for key, value in [("all", result["all"]), ("non_aime", result["non_aime"])] + \
            list(result["by_family"].items()) + [("aime_" + k, v) for k, v in result["aime_subsets"].items()]:
        if value.get("n"):
            print(f"{key:22s} n={value['n']:3d} 4k={value['accuracy_4k']:.3f} "
                  f"8k={value['accuracy_8k']:.3f} gain={value['gain']:+.3f} "
                  f"conv={value['conversions']} derail={value['derailments']} "
                  f"p={value['sign_p'] if value['sign_p'] is None else round(value['sign_p'], 4)} "
                  f"cap4={value['answer_cap_4k']:.2f} ans4={value['answer_tokens_4k_median']}")
    return result


if __name__ == "__main__":
    main()

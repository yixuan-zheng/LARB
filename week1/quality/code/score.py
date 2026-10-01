"""Score a generation run: per-example correctness and the per-schedule quality table.

Every schedule is compared with static_L on the same examples (paired), using the
rules frozen in manifests/quality_contract.json.

  python score.py --run-id <id>
"""
import argparse
import csv
import json
import math
import re

import numpy as np

from common import MANIFESTS, RESULTS

CONTRACT = json.loads((MANIFESTS / "quality_contract.json").read_text())
STOPS = CONTRACT["decoding"]["stop_strings"]
FLOOR_PP = -5.0
SEED = 6222
NUMBER = r"-?[\d,]*\.?\d+"


def extract(text):
    for stop in STOPS:
        text = text.split(stop)[0]
    candidates = re.findall(r"The answer is\s*\$?\s*(" + NUMBER + ")", text) or re.findall(NUMBER, text)
    return candidates[-1].replace(",", "") if candidates else None


def is_correct(pred, gold):
    return pred is not None and math.isclose(float(pred), float(gold))


def wilson(k, n, z=1.96):
    p = k / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return center - half, center + half


def paired_bootstrap(a, b, resamples=10_000, level=0.95):
    """CI for mean(a - b) in percentage points, resampling examples (pairs stay together)."""
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(a), size=(resamples, len(a)))
    diffs = 100 * (a[idx] - b[idx]).mean(axis=1)
    tail = 100 * (1 - level) / 2
    return np.percentile(diffs, tail), np.percentile(diffs, 100 - tail)


def mcnemar(a, b):
    """Exact two-sided McNemar p-value: only examples where the two disagree carry information."""
    only_a, only_b = int((a > b).sum()), int((b > a).sum())
    n = only_a + only_b
    if n == 0:
        return 1.0, only_a, only_b
    tail = sum(math.comb(n, k) for k in range(min(only_a, only_b) + 1)) / 2 ** n
    return min(1.0, 2 * tail), only_a, only_b


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    run_dir = RESULTS / args.run_id
    gold = {row["id"]: row["answer"] for row in map(json.loads, (MANIFESTS / "gsm8k_eval.jsonl").open())}
    rows = [json.loads(line) for line in (run_dir / "generations.jsonl").open()]
    schedules = json.loads((run_dir / "manifest.json").read_text())["schedules"]

    by_schedule = {}
    with (run_dir / "scored.jsonl").open("w") as f:
        for row in rows:
            pred = extract(row["text"])
            row["correct"] = is_correct(pred, gold[row["id"]])
            row["no_answer"] = pred is None
            by_schedule.setdefault(row["schedule"], {})[row["id"]] = row
            f.write(json.dumps({"schedule": row["schedule"], "id": row["id"], "pred": pred,
                                "gold": gold[row["id"]], "correct": row["correct"]}) + "\n")

    assert "static_L" in by_schedule, "static_L is the reference and must be in the run"
    reference = by_schedule["static_L"]
    table = []
    for schedule in [s for s in schedules if s in by_schedule]:
        results = by_schedule[schedule]
        ids = sorted(set(results) & set(reference))  # paired: examples finished under both
        sched = np.array([results[i]["correct"] for i in ids], dtype=float)
        ref = np.array([reference[i]["correct"] for i in ids], dtype=float)
        n, k = len(ids), int(sched.sum())
        lo, hi = wilson(k, n)
        delta = 100 * (sched.mean() - ref.mean())
        delta_lo, delta_hi = paired_bootstrap(sched, ref)
        p, ref_only, sched_only = mcnemar(ref, sched)
        picked = [results[i] for i in ids]
        table.append({
            "schedule": schedule, "split": picked[0]["split"], "n": n, "correct": k,
            "accuracy": round(100 * k / n, 2), "acc_lo": round(100 * lo, 2), "acc_hi": round(100 * hi, 2),
            "delta_pp": round(delta, 2), "delta_lo": round(delta_lo, 2), "delta_hi": round(delta_hi, 2),
            "mcnemar_p": round(p, 4), "static_L_only": ref_only, "schedule_only": sched_only,
            # non-inferiority: the whole CI must clear the floor, not just the point estimate
            "floor": "pass" if delta_lo >= FLOOR_PP else "not_established" if delta >= FLOOR_PP else "fail",
            "no_answer": sum(r["no_answer"] for r in picked),
            "hit_max_len": sum(r["stop_reason"] == "length" for r in picked),
            "mean_generated_len": round(np.mean([r["generated_len"] for r in picked]), 1),
            "frac_switched": round(np.mean([r["n_switches"] > 0 for r in picked]), 3),
            "mean_switches": round(np.mean([r["n_switches"] for r in picked]), 2),
            "frac_small": round(np.mean([r["frac_small"] for r in picked]), 3),
            "run_id": args.run_id,
        })

    with (run_dir / "quality_table.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=table[0].keys())
        writer.writeheader()
        writer.writerows(table)
    for r in table:
        print(f"{r['schedule']:9} n={r['n']:3} acc={r['accuracy']:5.1f} [{r['acc_lo']:.1f}, {r['acc_hi']:.1f}]  "
              f"delta={r['delta_pp']:+5.1f} pp [{r['delta_lo']:+.1f}, {r['delta_hi']:+.1f}]  "
              f"p={r['mcnemar_p']:.3f}  floor={r['floor']}  switched={r['frac_switched']:.0%}")
    print(f"wrote {run_dir / 'quality_table.csv'} and scored.jsonl")


if __name__ == "__main__":
    main()

"""Score held-out allocations using the completed, paired Omni-MATH grid."""

import collections
import itertools
import json
import os
import random
import statistics
from pathlib import Path

root = Path(os.environ["AUDIT_ROOT"])
source = Path.home() / "scratch/larb-math-repair-20261118"
freeze = json.loads((source / "freeze.json").read_text())
held = [q for i, q in enumerate(freeze["smoke"]) if i % 3 != 0]
questions = [q["question_id"] for q in held]
budgets = list(freeze["budgets"].values())
grid = {}
for row in held:
    qid = row["question_id"]
    for budget in budgets:
        rows = [json.loads((source / "smoke/solves" /
                f"smoke--fixed{budget}--{qid}--{seed}.json").read_text())
                for seed in freeze["seeds"]]
        grid[qid, budget] = dict(
            accuracy=statistics.mean(r["correct"] for r in rows),
            total_tokens=statistics.mean(r["prompt_tokens"]+r["output_tokens"] for r in rows),
            output_tokens=statistics.mean(r["output_tokens"] for r in rows),
            solver_seconds=statistics.mean(r["seconds"] for r in rows))

def stats(assignment):
    rows = [grid[q, b] for q, b in zip(questions, assignment)]
    return {key: statistics.mean(row[key] for row in rows) for key in rows[0]}

fixed = {b:stats([b]*len(questions)) for b in budgets}
epochs = random.Random(2461)
samples = [[epochs.randrange(len(questions)) for _ in questions] for _ in range(5000)]
def score_variant(rows):
    predictions = {r["question_id"]:r for r in rows}
    assert set(predictions) == set(questions) and len(rows) == len(questions)
    chosen = [predictions[q]["budget"] for q in questions]
    counts = collections.Counter(chosen)
    result = stats(chosen)
    overhead = {key:statistics.mean(r[key] for r in rows)
                for key in ("input_tokens","output_tokens","seconds")}
    charged = result["total_tokens"] + overhead["input_tokens"] + overhead["output_tokens"]
    ranked = sorted(range(len(held)), key=lambda i:(held[i]["prompt_tokens"],questions[i]))
    assigned = dict(zip(ranked, sorted(chosen)))
    length = stats([assigned[i] for i in range(len(held))])
    shuffled = {key:sum(fixed[b][key]*count for b,count in counts.items())/len(held)
                for key in next(iter(fixed.values()))}
    # A convex mixture of two fixed caps is a generous question-independent control.
    # Include the histogram-matched random allocation and interpolate at the charged cost.
    controls = list(fixed.values())+[shuffled]
    feasible = [p["accuracy"] for p in controls if p["total_tokens"] <= charged]
    for a,b in itertools.permutations(controls,2):
        if a["total_tokens"] < charged < b["total_tokens"]:
            t = (charged-a["total_tokens"])/(b["total_tokens"]-a["total_tokens"])
            feasible.append(a["accuracy"]+t*(b["accuracy"]-a["accuracy"]))
    diffs = [grid[q,b]["accuracy"]-sum(grid[q,x]["accuracy"]*n
             for x,n in counts.items())/len(held) for q,b in zip(questions,chosen)]
    interval = sorted(statistics.mean(diffs[i] for i in sample) for sample in samples)
    grows = [grid[q,budgets[-1]]["accuracy"] > grid[q,budgets[0]]["accuracy"] for q in questions]
    return dict(model=result, charged_total_tokens=charged, overhead=overhead, counts=counts,
                invalid=sum(not r["valid"] for r in rows), length=length, shuffled=shuffled,
                equal_cost_control=max(feasible,default=None),
                lift_vs_shuffle_ci=[statistics.mean(diffs),interval[125],interval[4874]],
                mean_cap_by_observed_8k_gain={
                    str(flag):statistics.mean(b for b,g in zip(chosen,grows) if g==flag)
                    for flag in set(grows)})

length_order = sorted(held, key=lambda r:(r["prompt_tokens"],r["question_id"]))
balanced_length = dict(zip((r["question_id"] for r in length_order),
                           sorted(budgets * (len(held)//len(budgets)))))
result = {"balanced_length":stats([balanced_length[q] for q in questions]),
          "questions":len(held), "trials_per_budget":2*len(held), "fixed":fixed,
          "original":score_variant([dict(question_id=q,budget=2048,input_tokens=len(row["selector_ids"]),
              output_tokens=3,seconds=0.05370812178201353,valid=True) for q,row in zip(questions,held)])}
for name in ("original_reverse","rubric","examples","difficulty"):
    path = root / f"{name}.jsonl"
    if path.exists():
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if len(rows) == len(questions):
            result[name] = score_variant(rows)
print(json.dumps(result,indent=2))

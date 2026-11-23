"""Held-out paired evaluation against forced modes, mixtures and shuffled modes."""
import json
from collections import Counter
from pathlib import Path

import numpy as np


def summary(arms, mode):
    chosen = arms[np.arange(len(arms)), mode]
    return {"accuracy":float(chosen[:,0].mean()), "mean_tokens":float(chosen[:,1].mean())}


def frontier(fixed, tokens):
    candidates = [point["accuracy"] for point in fixed if point["mean_tokens"] <= tokens]
    for left in fixed:
        for right in fixed:
            low, high = left["mean_tokens"], right["mean_tokens"]
            if low < high and low <= tokens <= high:
                weight = (tokens-low)/(high-low)
                candidates.append(left["accuracy"]*(1-weight)+right["accuracy"]*weight)
    return max(candidates, default=None)


def main():
    path = Path("evaluation.jsonl")
    if not path.is_file():
        return
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    arms = np.array([[[arm["correct"],arm["total_tokens"]] for arm in row["arms"]] for row in rows])
    modes = np.array([row["selected"] for row in rows])
    weights = np.bincount(modes, minlength=3)/len(rows)
    fixed = [summary(arms, i) for i in range(3)]
    adaptive = summary(arms, modes)
    shuffled = dict(zip(("accuracy","mean_tokens"), (arms.mean(axis=0).T@weights).tolist()))
    route_cost = float(np.mean([row["route_prefill_tokens"] for row in rows]))
    adaptive["mean_tokens"] += route_cost
    shuffled["mean_tokens"] += route_cost
    # The realized fixed mixture frontier can interpolate between any two caps.
    matched = frontier(fixed, adaptive["mean_tokens"])
    rng = np.random.default_rng(1321)
    indices = rng.integers(len(rows), size=(4000,len(rows)))
    oracle = arms[np.arange(len(rows)),modes]
    expected_shuffle = arms.transpose(0,2,1)@weights
    interval = np.quantile((oracle-expected_shuffle)[indices].mean(axis=1), [.025,.975], axis=0)
    result = dict(evaluated=len(rows), planned=len(json.loads(Path("freeze.json").read_text())["evaluation"]),
                  adaptive=adaptive, fixed=dict(zip(("Low","Medium","High"),fixed)), shuffled=shuffled,
                  fixed_frontier_accuracy_at_adaptive_tokens=matched,
                  route_counts=dict(Counter(map(int,modes))), mean_route_prefill_tokens=route_cost,
                  paired_adaptive_minus_shuffle_interval=interval.tolist(),
                  median_route_prefill_seconds=float(np.median([r["route_seconds"] for r in rows])),
                  median_three_mode_batch_seconds=float(np.median([r["batch_seconds"] for r in rows])))
    Path("evaluation-summary.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

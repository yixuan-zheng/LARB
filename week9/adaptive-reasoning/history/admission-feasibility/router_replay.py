"""Question-held-out 4K/8K routing with predicted incremental token cost."""

import json
import sys
from pathlib import Path

import numpy as np


def design(features):
    base = np.column_stack((np.ones(len(features)), features))
    return np.block([[base, np.zeros_like(base)], [base, base]])


def sigmoid(logits):
    return 1 / (1 + np.exp(-np.clip(logits, -40, 40)))


def fit_scores(inputs, rates, costs, folds, *, prefill):
    scores = {key: np.empty(len(inputs)) for key in ("risk", "gain", "value")}
    for fold in np.unique(folds):
        train = folds != fold
        features = inputs - inputs[train].mean(axis=0)
        if prefill:
            _, scale, axes = np.linalg.svd(features[train], full_matrices=False)
            features = features @ axes[:4].T / (scale[:4] / np.sqrt(train.sum()))
        else:
            features /= features[train].std(axis=0)

        width = features.shape[1]
        train_design = design(features[train])
        penalty = np.diag([.01] + [1] * width + [.01] + [2] * width)
        accuracy = rates[train].T.ravel()
        weights = np.zeros(train_design.shape[1])
        for _ in range(35):
            fitted = sigmoid(train_design @ weights)
            curvature = train_design * (fitted * (1 - fitted))[:, None]
            weights += np.linalg.solve(
                train_design.T @ curvature + penalty,
                train_design.T @ (accuracy - fitted) - penalty @ weights,
            )
        cost_weights = np.linalg.solve(
            train_design.T @ train_design + penalty,
            train_design.T @ costs[train].T.ravel(),
        )
        holdout = design(features[~train])
        low, high = sigmoid(holdout @ weights).reshape(2, -1)
        low_cost, high_cost = (holdout @ cost_weights).reshape(2, -1)
        scores["risk"][~train] = 1 - low
        scores["gain"][~train] = high - low
        scores["value"][~train] = (high - low) / np.maximum(1, high_cost - low_cost)
    return scores


def replay(scores, added_cost, target):
    """Compare rankings at equal realized cost, fractionally resolving ties."""
    selected = np.zeros(len(scores))
    groups = [scores == value for value in np.unique(scores)[::-1]]
    group_costs = [added_cost[mask].sum() for mask in groups]
    # Reserve the savings first so a low-ranked negative-cost group cannot
    # leave a higher-ranked group needlessly below the common token target.
    target -= sum(cost for cost in group_costs if cost <= 0)
    for mask, group_cost in zip(groups, group_costs):
        if group_cost <= 0:
            selected[mask] = 1
            continue
        fraction = np.clip(target / group_cost, 0, 1)
        selected[mask] = fraction
        target -= group_cost * fraction
    return selected


def main(root):
    frozen = json.loads((root / "freeze.json").read_text())
    ids = [row["question_id"] for row in frozen["questions"]]
    runs = []
    for qid in ids:
        for cap in frozen["budgets"]:
            for seed in frozen["seeds"]:
                path = root / "smoke" / "solves" / f"admission--fixed{cap}--{qid}--{seed}.json"
                row = json.loads(path.read_text())
                assert row["complete"] and (row["question_id"], row["budget"], row["seed"]) == (qid, cap, seed)
                runs.append((int(row["correct"]), row["prompt_tokens"] + row["output_tokens"]))
    assert frozen["budgets"] == [4096, 8192]
    rates, costs = np.array(runs).reshape(len(ids), 2, len(frozen["seeds"]), 2).mean(axis=2).transpose(2, 0, 1)
    gain = rates[:, 1] - rates[:, 0]
    added_cost = costs[:, 1] - costs[:, 0]
    folds = np.array([frozen["folds"][qid] for qid in ids])
    length = np.log1p([row["prompt_tokens"] for row in frozen["questions"]])
    archive = np.load(root / "prefill.npz")
    assert archive["keys"].tolist() == ids
    scores = {"raw_length": length, "uniform": np.zeros(len(ids))}
    for name, inputs in (("length", length[:, None]), ("prefill", archive["X"].astype(float))):
        scores.update({
            f"{name}_{key}": value
            for key, value in fit_scores(inputs, rates, costs, folds, prefill=name == "prefill").items()
        })
    random = np.random.default_rng(2026)
    for fraction in (.25, .5, .75):
        results = {}
        contributions = {}
        for name, score in scores.items():
            for fee in ((0, 25, 100) if name.startswith("prefill") else (0,)):
                selected = replay(score, added_cost, fraction * added_cost.sum() - len(ids) * fee)
                contribution = selected * gain
                contributions[name, fee] = contribution
                results[f"{name}_{fee}"] = {
                    "accuracy": (rates[:, 0] + contribution).mean(),
                    "tokens_with_fee": (costs[:, 0] + selected * added_cost).mean() + fee,
                }
        draws = random.integers(len(ids), size=(10000, len(ids)))
        for name in ("length", "prefill"):
            delta = contributions[f"{name}_value", 0] - contributions[f"{name}_risk", 0]
            results[f"{name}_value_minus_risk_conditional_interval"] = np.quantile(
                delta[draws].mean(axis=1), (.025, .975)
            ).tolist()
        print(json.dumps({"fraction_incremental_compute": fraction, "results": results}))


if __name__ == "__main__":
    main(Path(sys.argv[1]))

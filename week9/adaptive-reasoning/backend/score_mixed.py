"""Summarize same-checkpoint mixed-workload evidence."""
import json
from pathlib import Path

import numpy as np
from score import frontier, summary


def read(name):
    p = Path(name)
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


def arrays(rows):
    return np.array([[[a["correct"], a["total_tokens"]] for a in r["arms"]] for r in rows])


def main():
    rows = read("evaluation.jsonl")
    if not rows:
        return
    arms = arrays(rows)
    route = np.array([r["selected"] for r in rows])
    overhead = np.mean([r["route_prefill_tokens"] for r in rows])
    selected = arms[np.arange(len(rows)),route]
    fixed = [summary(arms,i) for i in range(3)]
    adaptive = summary(arms,route)
    adaptive["mean_tokens"] += overhead
    weights = np.bincount(route,minlength=3)/len(rows)
    expected = arms.transpose(0,2,1)@weights
    by_source = {}
    within = np.zeros_like(expected)
    for source in sorted({r["stratum"] for r in rows}):
        bucket = np.array([r["stratum"] == source for r in rows])
        source_weights = np.bincount(route[bucket],minlength=3)/bucket.sum()
        within[bucket] = arms[bucket].transpose(0,2,1)@source_weights
        by_source[source] = dict(n=int(bucket.sum()), routing=source_weights.tolist(),
                                 accuracy=float(selected[bucket,0].mean()),
                                 fixed_accuracy=arms[bucket,:,0].mean(axis=0).tolist())
    dev = read("development.jsonl")
    cheap = None
    if dev and {r["stratum"] for r in dev} >= set(by_source):
        candidates = {}
        for price in (0.,.04,.08,.16,.32,.64):
            rule = {}
            for source in by_source:
                subset = [r for r in dev if r["stratum"] == source]
                midpoint = np.median([r["problem_words"] for r in subset])
                choices = []
                for short in (True,False):
                    group = [r for r in subset if (r["problem_words"]<=midpoint)==short] or subset
                    outcomes = arrays(group).mean(axis=0)
                    choices.append(int((outcomes[:,0]-price*outcomes[:,1]/8192).argmax()))
                rule[source] = (midpoint, choices)
            dev_modes = [rule[r["stratum"]][1][int(r["problem_words"]>rule[r["stratum"]][0])] for r in dev]
            dev_point = summary(arrays(dev),dev_modes)
            candidates[price] = (dev_point,rule)
        eligible = [r for r in candidates.values() if r[0]["mean_tokens"] <= adaptive["mean_tokens"]]
        if eligible:
            _, rule = max(eligible,key=lambda r:r[0]["accuracy"])
            cheap = summary(arms,[rule[r["stratum"]][1][int(r["problem_words"]>rule[r["stratum"]][0])] for r in rows])
    rng = np.random.default_rng(1019)
    boot = rng.integers(len(rows),size=(4000,len(rows)))

    def shuffled(value):
        delta = (selected-value)[boot].mean(axis=1)
        return dict(accuracy=float(value[:,0].mean()),mean_tokens=float(value[:,1].mean()+overhead),
                    adaptive_minus_shuffle_interval=np.quantile(delta,[.025,.975],axis=0).tolist())

    result = dict(n=len(rows), fixed=fixed, adaptive=adaptive, global_shuffle=shuffled(expected),
                  within_source_shuffle=shuffled(within), source_length=cheap, by_source=by_source,
                  fixed_frontier_at_adaptive_tokens=frontier(fixed,adaptive["mean_tokens"]),
                  fixed_frontier_at_10pct_more_compute=frontier(fixed,adaptive["mean_tokens"]/.9),
                  mean_route_prefill_tokens=float(overhead),
                  median_route_prefill_seconds=float(np.median([r["route_seconds"] for r in rows])))
    Path("evaluation-summary.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

"""Paired pilot summaries; no unsupported serving generalization."""

import json, csv, random, statistics
from pathlib import Path

root = Path(__file__).resolve().parent.parent
out = root / "results"
r = json.loads((out / "experiment.json").read_text())
result = {
    "completed": r.get("completed", False),
    "calibration": r.get("calibration"),
    "quality": r.get("quality"),
    "quality_loss_intervals": {},
    "policy_aggregate": {},
}
articles = {
    x["id"]: x["article"]
    for x in json.loads((root / "data/workload.json").read_text())["evaluation"]
}


def interval(deltas, labels):
    rng = random.Random(47)
    n = len(deltas)
    groups = {}
    for d, label in zip(deltas, labels):
        groups.setdefault(label, []).append(d)
    clusters = list(groups.values())
    samples = []
    for _ in range(5000):
        picked = rng.choices(clusters, k=len(clusters))
        samples.append(sum(sum(g) for g in picked) / sum(len(g) for g in picked) * 100)
    samples.sort()
    return {
        "mean_loss_pp": statistics.mean(deltas) * 100,
        "lower95_pp": samples[124],
        "upper95_pp": samples[4874],
        "paired_examples": n,
        "article_clusters": len(clusters),
        "interval_method": "paired article-cluster bootstrap; repeated replay examples averaged",
        "quality_gate_pass": samples[4874] <= 5,
    }


if (out / "quality_large.json").exists():
    base = {x["id"]: x for x in json.loads((out / "quality_large.json").read_text())}
    for mode in ["small", "hybrid"]:
        p = out / f"quality_{mode}.json"
        if p.exists():
            rows = json.loads(p.read_text())
            result["quality_loss_intervals"][mode] = interval(
                [base[x["id"]]["em"] - x["em"] for x in rows],
                [articles[x["id"]] for x in rows],
            )
policies = ["large", "small", "fixed_hybrid", "adaptive"]
deltas = {}
replay = []
for p in sorted(out.glob("replay_*.json")):
    v = json.loads(p.read_text())
    replay.append(v)
bykey = {(x["summary"]["seed"], x["summary"]["policy"]): x for x in replay}
for mode in policies:
    group = [v for v in replay if v["summary"]["policy"] == mode]
    if not group:
        continue
    summaries = [x["summary"] for x in group]
    total = sum(x["requests"] for x in summaries)
    duration = sum(x["wall_seconds"] for x in summaries)
    result["policy_aggregate"][mode] = {
        "traces": len(group),
        "goodput": sum(x["goodput"] * x["wall_seconds"] for x in summaries) / duration,
        "throughput": total / duration,
        "em": sum(x["em"] * x["requests"] for x in summaries) / total,
        "slo_pass_rate": sum(x["slo_pass_rate"] * x["requests"] for x in summaries)
        / total,
        "small_prefill_fraction": sum(
            x["small_prefill_fraction"] * x["requests"] for x in summaries
        )
        / total,
        "mean_batch": statistics.mean(x["mean_batch"] for x in summaries),
        "max_queue": max(x["max_queue"] for x in summaries),
    }
    if mode != "large":
        pairs = {}
        for v in group:
            b = bykey.get((v["summary"]["seed"], "large"))
            if not b:
                continue
            b = {x["id"]: x["em"] for x in b["requests"]}
            for x in v["requests"]:
                pairs.setdefault(x["id"], []).append(b[x["id"]] - x["em"])
        if pairs:
            result["quality_loss_intervals"][mode + "_replay"] = interval(
                [statistics.mean(x) for x in pairs.values()],
                [articles[k] for k in pairs],
            )
result["per_trace"] = r.get("traces", [])
agg = result["policy_aggregate"]
comparisons = {}
for mode in ["adaptive", "fixed_hybrid"]:
    if mode not in agg:
        continue
    for baseline in [x for x in policies if x != mode]:
        if baseline not in agg:
            continue
        b = agg[baseline]["goodput"]
        wins = []
        for seed in [11, 22, 33]:
            x, y = bykey.get((seed, mode)), bykey.get((seed, baseline))
            if x and y:
                wins.append(x["summary"]["goodput"] > y["summary"]["goodput"])
        comparisons[mode + "_vs_" + baseline] = {
            "goodput_gain_percent": 100 * (agg[mode]["goodput"] / b - 1) if b else None,
            "absolute_gain_requests_s": agg[mode]["goodput"] - b,
            "traces_won": sum(wins),
            "traces_compared": len(wins),
        }
result["comparisons"] = comparisons
(out / "analysis.json").write_text(json.dumps(result, indent=2) + "\n")
if r.get("traces"):
    with (out / "comparison.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(r["traces"][0]))
        writer.writeheader()
        writer.writerows(r["traces"])
print(json.dumps(result, indent=2))

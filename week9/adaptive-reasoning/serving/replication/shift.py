"""Freeze source composition shifts and compare cached allocation policies."""
import json
import random
import statistics
import sys
from pathlib import Path

run, original, replication = map(Path,sys.argv[1:])
manifest = json.loads((run/"freeze.json").read_text())
observations = {r["question_id"]:r for r in map(json.loads,(run/"evaluation.jsonl").read_text().splitlines())}
balanced = json.loads(original.read_text())
reference = balanced["pilot_holdout"]
sources = ("gsm8k","math","omni")
rates = {source:statistics.mean(row["selected"]==2 for row in reference if row["source"]==source)
         for source in sources}
prior = json.loads(replication.read_text())
reserve = {row["question_id"] for row in prior["blocks"][2]["questions"]+prior["reserve"]}
pool = {}
for source in sources:
    rows = sorted((row for row in manifest["evaluation"] if row["source"]==source
                   and row["question_id"] in observations),key=lambda r:r["question_id"])
    rng=random.Random("shift-pool:"+source)
    rng.shuffle(rows)
    pool[source]=sorted(rows,key=lambda r:r["question_id"] not in reserve)


def randomized(rows,seed,*,conditional):
    rng=random.Random(seed)
    result={}
    for source in sources:
        group=[r for r in rows if r["source"]==source]
        if conditional:
            modes=[observations[r["question_id"]]["selected"] for r in group]
        else:
            high=round(len(group)*rates[source])
            modes=[2]*high+[1]*(len(group)-high)
        rng.shuffle(modes)
        result.update((r["question_id"],m) for r,m in zip(group,modes,strict=True))
    return result


def measure(rows,policy):
    scored=[observations[r["question_id"]]["arms"][policy[r["question_id"]]] for r in rows]
    return dict(correct=sum(r["correct"] for r in scored),
                mean_solver_tokens=statistics.mean(r["total_tokens"] for r in scored))


result=dict(reference_high_rates=rates,live_seed=151,scenarios={})
for name,sizes in (("balanced",(8,8,8)),("omni-heavy",(4,4,16)),("gsm-heavy",(16,4,4))):
    rows=[r for source,count in zip(sources,sizes,strict=True) for r in pool[source][:count]]
    policy={r["question_id"]:observations[r["question_id"]]["selected"] for r in rows}
    benchmarks={f"fixed-{m}":measure(rows,{r["question_id"]:m for r in rows}) for m in (0,1,2)}
    simulations={}
    for label,conditional in (("within-source-shuffle",True),("frozen-source-random",False)):
        draws=[measure(rows,randomized(rows,seed,conditional=conditional)) for seed in range(1000)]
        simulations[label]=dict(mean_correct=statistics.mean(d["correct"] for d in draws),
            mean_solver_tokens=statistics.mean(d["mean_solver_tokens"] for d in draws),
            seed151=measure(rows,randomized(rows,151,conditional=conditional)))
    result["scenarios"][name]=dict(source_counts=dict(zip(sources,sizes)),
        learned=measure(rows,policy),high_routes=sum(m==2 for m in policy.values()),
        high_only_success=sum(x[2]["correct"] and not (x[1]["correct"] or x[0]["correct"])
                              for x in (observations[r["question_id"]]["arms"] for r in rows)),
        frozen_high_routes=sum(m==2 for m in randomized(rows,151,conditional=False).values()),
        fixed=benchmarks,random_controls=simulations)
    if name=="omni-heavy":
        within=randomized(rows,151,conditional=True)
        frozen=randomized(rows,151,conditional=False)
        selected=[dict(r,selected=policy[r["question_id"]],shuffle_mode=within[r["question_id"]],
                       frozen_mode=frozen[r["question_id"]]) for r in rows]
        random.Random(29209).shuffle(selected)
        Path("freeze.json").write_text(json.dumps(dict(balanced,pilot_holdout=selected,
            shift=name,shuffle_seed=151,frozen_reference_high_rates=rates),indent=2)+"\n")
Path("shift-offline.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result))

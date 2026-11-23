"""Calibrate a deployable Medium/High coin on development only."""
import json
import random
import statistics
import sys
from pathlib import Path

run = Path(sys.argv[1])


def read(name):
    return [json.loads(line) for line in (run/name).read_text().splitlines()]


def point(rows, probabilities):
    return dict(accuracy=statistics.mean((1-p)*r["arms"][1]["correct"]+p*r["arms"][2]["correct"]
                                         for r,p in zip(rows,probabilities,strict=True)),
                tokens=statistics.mean((1-p)*r["arms"][1]["total_tokens"]+p*r["arms"][2]["total_tokens"]
                                       for r,p in zip(rows,probabilities,strict=True)))


dev=read("development.jsonl")
# Spend as little as possible subject to a five-point expected development
# accuracy tolerance versus fixed High. Use the fixed 10-point probability grid.
high=point(dev,[1]*len(dev))
grid=[(k/10,point(dev,[k/10]*len(dev))) for k in range(11)]
p,dev_choice=min((x for x in grid if x[1]["accuracy"] >= high["accuracy"]-.05-1e-12),
                 key=lambda x:(x[1]["tokens"],x[0]))
rows=read("evaluation.jsonl")
n=len(rows)
rates={s:statistics.mean(r["selected"]==2 for r in rows if r["stratum"]==s)
       for s in {r["stratum"] for r in rows}}
rng=random.Random(151)
chosen=[int(rng.random()<p) for _ in rows]
out=dict(development_n=len(dev),development_fixed_high=high,development_choice=dev_choice,
    high_probability=p,evaluation_n=n,global_expected=point(rows,[p]*n),
    global_seed151=point(rows,chosen),seed151_high=sum(chosen),
    learned=point(rows,[int(r["selected"]==2) for r in rows]),
    within_source_shuffle=point(rows,[rates[r["stratum"]] for r in rows]),
    fixed_medium=point(rows,[0]*n),fixed_high=point(rows,[1]*n),
    router_prefill_tokens=statistics.mean(r["route_prefill_tokens"] for r in rows))
print(json.dumps(out,indent=2))

"""Outcome-blind within-source difficulty stress using reference solutions."""
import hashlib
import json
import random
import re
import statistics
import sys
from pathlib import Path

import pyarrow.parquet as pq

run, data, omni, original, pilot = map(Path,sys.argv[1:])
sources = ("gsm8k","math","omni")


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def key(text):
    return " ".join(text.split())


reference = {
    "gsm8k": {key(r["question"]):r["answer"].split("####")[0]
               for r in pq.read_table(data/"gsm-test.parquet").to_pylist()},
    "math": {key(r["problem"]):r["solution"] for r in jsonl(data/"math-500.jsonl")},
    "omni": {key(r["problem"]):r["solution"] for r in jsonl(omni)},
}
base = json.loads(original.read_text())
excluded = {r["question_id"] for r in base["pilot_holdout"]+json.loads(pilot.read_text())["pilot_holdout"]}
manifest = json.loads((run/"freeze.json").read_text())
available = {r["question_id"] for r in jsonl(run/"evaluation.jsonl")}
rows = []
picks = {}
# Invert the source prior using the top GSM8K and MATH tails and the bottom
# Omni-MATH tail. Rank by reference length, with digest ties, before scoring.
for source in sources:
    pool = [r for r in manifest["evaluation"] if r["source"]==source and r["question_id"] not in excluded
            and r["question_id"] in available]
    for row in pool:
        sol = reference[source][key(row["problem"])]
        row["reference_steps_proxy"] = len(re.findall(r"\w+|[^\w\s]", sol))
    direction = 1 if source=="omni" else -1
    pool.sort(key=lambda r:(direction*r["reference_steps_proxy"],hashlib.sha256(r["question_id"].encode()).digest()))
    assert len(pool)>=4
    picks[source] = dict(pool=len(pool),median_proxy=statistics.median(r["reference_steps_proxy"] for r in pool),
                         selected_proxy=[r["reference_steps_proxy"] for r in pool[:4]])
    rows.extend(pool[:4])

observed = {r["question_id"]:r for r in jsonl(run/"evaluation.jsonl")}
rates = {s:statistics.mean(r["selected"]==2 for r in base["pilot_holdout"] if r["source"]==s) for s in sources}
learned = {r["question_id"]:observed[r["question_id"]]["selected"] for r in rows}


def random_modes(seed,freeze):
    rng=random.Random(seed)
    assigned={}
    for source in sources:
        ids=[r["question_id"] for r in rows if r["source"]==source]
        high=round(len(ids)*rates[source])
        modes=([2]*high+[1]*(len(ids)-high)) if freeze else [learned[k] for k in ids]
        rng.shuffle(modes)
        assigned.update(zip(ids,modes,strict=True))
    return assigned


def score(policy):
    arms=[observed[qid]["arms"][mode] for qid,mode in policy.items()]
    return sum(a["correct"] for a in arms),statistics.mean(a["total_tokens"] for a in arms)


result=dict(selection=picks, reference_high_rates=rates, learned=score(learned),
    learned_high_by_source={s:sum(learned[r["question_id"]]==2 for r in rows if r["source"]==s) for s in sources})
for freeze in (False,True):
    scores=[score(random_modes(seed,freeze)) for seed in range(1000)]
    result["frozen" if freeze else "shuffle"]=dict(mean=[statistics.mean(x) for x in zip(*scores)],
                                                   seed151=score(random_modes(151,freeze)))
result["fixed"]={mode:score({qid:mode for qid in learned}) for mode in (0,1,2)}
result["fixed_by_source"]={s:{mode:score({r["question_id"]:mode for r in rows if r["source"]==s})
                                for mode in (0,1,2)} for s in sources}
within,frozen=random_modes(151,False),random_modes(151,True)
selected=[dict(r,selected=learned[r["question_id"]],shuffle_mode=within[r["question_id"]],
               frozen_mode=frozen[r["question_id"]]) for r in rows]
random.Random(28231).shuffle(selected)
Path("freeze.json").write_text(json.dumps(dict(base,pilot_holdout=selected,shift="within-source",
    live_seed=151,selection=picks),indent=2)+"\n")
Path("within-source-offline.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result))

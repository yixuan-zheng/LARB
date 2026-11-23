"""Freeze independent workload blocks and within-source mode shuffles."""
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

run, pilot, output = map(Path, sys.argv[1:])
freeze = json.loads((run / "freeze.json").read_text())
previous = json.loads(pilot.read_text())
excluded = {row["question_id"] for row in previous["pilot_holdout"]}
choices = {row["question_id"]: row["selected"] for row in
           map(json.loads, (run / "evaluation.jsonl").read_text().splitlines())}
sources = ("gsm8k", "math", "omni")
blocks = [[] for _ in range(3)]
reserve = []
for index, source in enumerate(sources):
    candidates = sorted((row for row in freeze["evaluation"]
                         if row["source"] == source and row["question_id"] in choices
                         and row["question_id"] not in excluded),
                        key=lambda row: row["question_id"])
    random.Random(40591 + index).shuffle(candidates)
    assert len(candidates) == 28
    for j, block in enumerate(blocks):
        block.extend(dict(row, selected=choices[row["question_id"]])
                     for row in candidates[j*8:(j+1)*8])
    reserve.extend(dict(row, selected=choices[row["question_id"]]) for row in candidates[24:])

for i, block in enumerate(blocks):
    # Keep mode and source balance independent of serving order.
    permutations = {}
    for seed in (71, 151, 411):
        mapping = {}
        for source in sources:
            members = [row for row in block if row["source"] == source]
            modes = [row["selected"] for row in members]
            shuffled = modes.copy()
            random.Random(f"shuffle:{i}:{seed}:{source}").shuffle(shuffled)
            mapping.update((row["question_id"], mode)
                           for row, mode in zip(members, shuffled, strict=True))
            assert Counter(shuffled) == Counter(modes)
        permutations[str(seed)] = mapping
    orders = {}
    for seed in (920011, 920087):
        ids = [row["question_id"] for row in block]
        random.Random(seed+i).shuffle(ids)
        orders[str(seed)] = ids
    blocks[i] = dict(name=f"mixed-{i+1}", questions=block, arrival_orders=orders,
                     within_source_shuffles=permutations)

all_ids = [row["question_id"] for b in blocks for row in b["questions"]]
all_ids.extend(row["question_id"] for row in reserve)
assert len(all_ids) == len(set(all_ids)) == 84
output.write_text(json.dumps(dict(blocks=blocks, reserve=reserve,
    route_source_sha256=hashlib.sha256((run / "evaluation.jsonl").read_bytes()).hexdigest(),
    prior_pilot_sha256=hashlib.sha256(pilot.read_bytes()).hexdigest()), indent=2)+"\n")
print("Frozen three blocks of 24 and 12 reserve questions")
for b in blocks:
    print(b["name"], dict(Counter(row["selected"] for row in b["questions"])),
          [sum(shuffle[row["question_id"]] != row["selected"] for row in b["questions"])
           for shuffle in b["within_source_shuffles"].values()])

"""Freeze one scored block and one disjoint development timing block."""
import json
import random
import sys
from pathlib import Path

run = Path(sys.argv[1])
data = json.loads((run/"freeze.json").read_text())
rng = random.Random(833437)


def select(split, records):
    choices = {r["question_id"]: r["selected"] for r in
               map(json.loads, (run/records).read_text().splitlines())}
    rows = []
    for source in ("gsm8k","math","omni"):
        candidates = [r for r in data[split] if r["source"]==source and r["question_id"] in choices]
        rng.shuffle(candidates)
        chosen = candidates[:4]
        assert len(chosen) == 4
        modes = [choices[r["question_id"]] for r in chosen]
        shuffled = modes.copy()
        rng.shuffle(shuffled)
        for row,mode,control in zip(chosen,modes,shuffled,strict=True):
            rows.append(dict(row,selected=mode,shuffle_mode=control))
    rng.shuffle(rows)
    return rows


scored = select("evaluation","evaluation.jsonl")
development = select("development","development.jsonl")
assert set(r["question_id"] for r in scored).isdisjoint(r["question_id"] for r in development)
Path("freeze.json").write_text(json.dumps(dict(pilot_holdout=scored,calibration=development),indent=2)+"\n")
print("Frozen scored modes",[(r["source"],r["selected"],r["shuffle_mode"]) for r in scored])

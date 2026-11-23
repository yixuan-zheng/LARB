"""Freeze an objective split, excluding questions from the prior pilot."""
import hashlib
import json
import random
import re
import sys
from pathlib import Path

source, old, out = map(Path, sys.argv[1:])
prior = json.loads(old.read_text())


def key(text):
    return hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()


excluded = {key(row["problem"]) for split in ("smoke", "calibration", "pilot_holdout")
            for row in prior[split]}
available = {label: [] for label in ("easy", "medium", "hard")}
for raw in source.read_text().splitlines():
    row = json.loads(raw)
    problem, answer = row["problem"], str(row["answer"]).strip()
    difficulty = float(row["difficulty"])
    qid = key(problem)
    if qid in excluded or not re.fullmatch(r"-?\d+", answer) or not 2 <= difficulty <= 7:
        continue
    if not 20 <= len(problem.split()) <= 180 or re.search(r"\b(figure|diagram|prove|shown below)\b", problem, re.I):
        continue
    excluded.add(qid)
    stratum = "easy" if difficulty < 4 else "medium" if difficulty < 6 else "hard"
    available[stratum].append(dict(question_id=qid[:20], problem=problem, answer=answer,
                                  difficulty=difficulty, stratum=stratum))
rng = random.Random(604923)
train, evaluation = [], []
for stratum, rows in available.items():
    rng.shuffle(rows)
    assert len(rows) >= 19, (stratum, len(rows))
    train += rows[:8]
    evaluation += rows[8:19]
rng.shuffle(train)
rng.shuffle(evaluation)
out.write_text(json.dumps(dict(train=train, evaluation=evaluation,
    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()), indent=2)+"\n")

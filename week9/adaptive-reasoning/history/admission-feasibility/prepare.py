"""Freeze previously reserved Omni-MATH questions for admission development."""

import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
source = Path(sys.argv[2])
raw = source.read_bytes()
prior = json.loads(raw)
questions = prior["pilot_holdout"]
assert len(questions) == len({q["question_id"] for q in questions}) == 24
assert {q["question_id"] for q in questions}.isdisjoint(
    q["question_id"] for q in prior["smoke"] + prior["calibration"])
folds = {q["question_id"]:i % 6 for i,q in enumerate(sorted(
    questions, key=lambda q:hashlib.sha256(("admission-feasibility:"+q["question_id"]).encode()).digest()))}
data = dict(source_sha256=hashlib.sha256(raw).hexdigest(),
            source_revision=prior["source_revision"], model_revision=prior["model_revision"],
            questions=questions, folds=folds, budgets=[4096,8192],
            seeds=[17,29,43,71], answer_cap=prior["answer_cap"])
(root / "freeze.json").write_text(json.dumps(data,indent=2)+"\n")

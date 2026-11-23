"""Prepare integer-answer train/dev/eval from pinned dataset files."""
import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq
from larb_scaled.grading import extract_boxed, normalise_answer

root, omni, past, screen, output = map(Path, sys.argv[1:])
rng = random.Random(173823)
normalized = set()
by_shingle = defaultdict(set)
grams = []


def deduplicate(problem):
    words = tuple(re.findall(r"[a-z]+|\d+|[^\w\s]", problem.casefold()))
    if words in normalized:
        return False
    new = set(zip(words, words[1:], words[2:], words[3:], words[4:]))
    overlaps = defaultdict(int)
    for shingle in new:
        for index in by_shingle[shingle]:
            overlaps[index] += 1
    if any(common / (len(new)+len(grams[index])-common) >= .8
           for index, common in overlaps.items()):
        return False
    normalized.add(words)
    for shingle in new:
        by_shingle[shingle].add(len(grams))
    grams.append(new)
    return True


def jsonl(path):
    return (json.loads(line) for line in path.read_text().splitlines() if line.strip())


def parquet(path):
    return pq.read_table(path).to_pylist()


def choose(rows, source, n):
    rows = list(rows)
    rng.shuffle(rows)
    output = []
    for row in rows:
        problem = row.get("problem") or row.get("question")
        if source == "gsm8k":
            answer = row["answer"].rsplit("####",1)[-1].strip().replace(",", "")
        elif source == "math" and "answer" not in row:
            answer = extract_boxed(row["solution"])["value"]
        else:
            answer = row["answer"]
        answer = normalise_answer(answer)
        if not re.fullmatch(r"-?\d+", answer):
            continue
        if not 10 <= len(problem.split()) <= 180 or re.search(r"\b(diagram|shown below|prove)\b", problem, re.I):
            continue
        if not deduplicate(problem):
            continue
        qid = hashlib.sha256(problem.encode()).hexdigest()[:20]
        output.append(dict(question_id=qid, source=source, stratum=source, problem=problem, answer=answer))
        if len(output) == n:
            return output
    raise ValueError(f"{source}: selected only {len(output)}/{n}")


old = json.loads(past.read_text())
earlier = json.loads(screen.read_text())
for row in [*old["smoke"], *old["calibration"], *old["pilot_holdout"],
            *earlier["train"], *earlier["evaluation"]]:
    deduplicate(row["problem"])

math_eval = root / "math-500.jsonl"
math_train = root / "math-train.parquet"
gsm_train = root / "gsm-train.parquet"
gsm_eval = root / "gsm-test.parquet"
eval_, dev, train = [], [], []
# Prioritize held-out sources before admitting overlapping training examples.
for source, rows in (("gsm8k", parquet(gsm_eval)), ("math", jsonl(math_eval)), ("omni", jsonl(omni))):
    eval_.extend(choose(rows, source, 64))
for source, rows, n in (("gsm8k", parquet(gsm_train), 171), ("math", parquet(math_train), 171),
                       ("omni", jsonl(omni), 170)):
    selected = choose(rows, source, n+16)
    dev.extend(selected[:16])
    train.extend(selected[16:])
assert len({r["question_id"] for r in train+dev+eval_}) == 752
for rows in (train, dev, eval_):
    rng.shuffle(rows)
output.write_text(json.dumps(dict(train=train, development=dev, evaluation=eval_,
    inputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (math_eval, math_train, gsm_train, gsm_eval, omni, past, screen)}), indent=2)+"\n")
print("Frozen", len(train), len(dev), len(eval_))

"""Deterministic trace generation and validation.

The trace is arm-agnostic. The replay client adds the arm and constructs the
runtime request key. Every arm in a condition replays the same bytes.
"""
import hashlib
import json
import math
import random
from datetime import datetime, timezone

from . import config

CONDITIONS = ("low", "sustained", "burst")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_questions():
    rows = {}
    with (config.DATA_DIR / "processed/questions.jsonl").open() as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows[row["question_id"]] = row
    return rows


def hash_rank(ids, salt):
    return sorted(ids, key=lambda qid: (hashlib.sha256(f"{salt}:{qid}".encode()).hexdigest(), qid))


def seed_for(protocol, question_index, seed_index):
    base = protocol["seeding"]["seed_base"]
    stride = protocol["seeding"]["question_stride"]
    return base + question_index * stride + seed_index


def _signal_rows(condition, cohort, questions, protocol, signal_limit=None, seeds=None):
    ids = list(cohort["main_ids"])
    cfg = protocol["workload"]["conditions"][condition]
    limit = signal_limit if signal_limit is not None else cfg["signal_questions"]
    limit = min(limit, len(ids))
    selected = hash_rank(ids, protocol["name"] + ":" + condition)[:limit]
    seed_count = seeds if seeds is not None else cfg["seeds"]
    rows = []
    for q_index, qid in enumerate(selected):
        q = questions[qid]
        for seed_index in range(seed_count):
            rows.append({
                "class": "signal",
                "question_id": qid,
                "seed": seed_for(protocol, q_index, seed_index),
                "prompt_sha256": q["prompt_sha256"],
                "reference": q["answer"],
                "source": q["pool"],
                "exposure": q["exposure"],
                "answer_type": q["answer_type"],
                "scored": True,
                "initial_budget": None,
            })
    return rows


def _filler_rows(condition, cohort, questions, protocol, signal_count, seed_count=4):
    filler_ids = list(cohort["filler_ids"])
    if not filler_ids:
        return []
    target = math.ceil(signal_count * protocol["workload"]["filler_share"] /
                       (1 - protocol["workload"]["filler_share"]))
    rows = []
    used = 0
    q_index = 0
    while len(rows) < target:
        qid = filler_ids[q_index % len(filler_ids)]
        q = questions[qid]
        seed = protocol["seeding"]["seed_base"] + 500000 + used
        rows.append({
            "class": "filler",
            "question_id": qid,
            "seed": seed,
            "prompt_sha256": q["prompt_sha256"],
            "reference": q["answer"],
            "source": q["pool"],
            "exposure": q["exposure"],
            "answer_type": q["answer_type"],
            "scored": False,
            "initial_budget": protocol["workload"]["filler_budget"],
        })
        used += 1
        if used % seed_count == 0:
            q_index += 1
    return rows


def _poisson_arrivals(rng, rate_per_hour, count, start_s=0.0):
    if rate_per_hour <= 0:
        raise ValueError("rate must be positive")
    rate = rate_per_hour / 3600.0
    times = []
    t = start_s
    for _ in range(count):
        t += rng.expovariate(rate)
        times.append(t)
    return times


def _assign_arrivals(condition, rows, protocol, rng):
    cfg = protocol["workload"]["conditions"][condition]
    if condition == "low":
        times = _poisson_arrivals(rng, cfg["provisional_rate_per_hour"], len(rows))
    elif condition == "sustained":
        times = _poisson_arrivals(rng, cfg["provisional_rate_per_hour"], len(rows))
    elif condition == "burst":
        burst_count = min(cfg["burst_count"], len(rows))
        pre_count = min(max(1, int(cfg["provisional_baseline_per_hour"] *
                              cfg["burst_start_s"] / 3600)), len(rows) - burst_count)
        post_count = len(rows) - burst_count - pre_count
        pre = _poisson_arrivals(rng, cfg["provisional_baseline_per_hour"], pre_count)
        burst_start = cfg["burst_start_s"]
        burst = [burst_start + i * cfg["burst_spacing_s"] for i in range(burst_count)]
        post_start = burst[-1] + cfg["burst_spacing_s"]
        post = _poisson_arrivals(rng, cfg["recovery_rate_per_hour"], post_count, post_start)
        times = pre + burst + post
    else:
        raise ValueError(condition)
    order = list(range(len(rows)))
    rng.shuffle(order)
    for slot, index in enumerate(order):
        rows[index]["arrival_s"] = round(times[slot], 6)
    return rows


def build_trace(condition, cohort, questions, protocol, signal_limit=None, seeds=None,
                seed=20261113):
    if condition not in CONDITIONS:
        raise ValueError(condition)
    rng = random.Random(f"{protocol['name']}:{condition}:{seed}")
    signal = _signal_rows(condition, cohort, questions, protocol, signal_limit, seeds)
    filler = _filler_rows(condition, cohort, questions, protocol, len(signal))
    rows = _assign_arrivals(condition, signal + filler, protocol, rng)
    deadline = protocol["deadline"]["slo_seconds"]
    for row in rows:
        row["condition"] = condition
        row["deadline_s"] = deadline
        row["trace_id"] = f"{condition}--{row['class']}--{row['question_id']}--{row['seed']}"
    rows.sort(key=lambda row: (row["arrival_s"], row["trace_id"]))
    validate_trace(rows, condition, protocol, cohort, questions)
    return rows


def build_gate_trace(name, ids_key, seeds, cohort, questions, protocol,
                     spacing_s=8.0, deadline_s=1800.0, limit=None):
    ids = list(cohort[ids_key])
    if limit is not None:
        ids = ids[:limit]
    rows = []
    index = 0
    for q_index, qid in enumerate(ids):
        q = questions[qid]
        for seed_index in range(seeds):
            rows.append({
                "trace_id": f"{name}--signal--{qid}--{seed_for(protocol, q_index, seed_index)}",
                "condition": name,
                "class": "signal",
                "question_id": qid,
                "seed": seed_for(protocol, q_index, seed_index),
                "arrival_s": round(index * spacing_s, 6),
                "deadline_s": deadline_s,
                "prompt_sha256": q["prompt_sha256"],
                "reference": q["answer"],
                "source": q["pool"],
                "exposure": q["exposure"],
                "answer_type": q["answer_type"],
                "scored": True,
                "initial_budget": None,
            })
            index += 1
    validate_trace(rows, name, protocol, cohort, questions, allowed_signal_ids=ids)
    return rows


def validate_trace(rows, condition, protocol, cohort, questions, allowed_signal_ids=None):
    if condition not in CONDITIONS and not condition.startswith("gate-"):
        raise ValueError(condition)
    allowed_signal = set(allowed_signal_ids if allowed_signal_ids is not None else cohort["main_ids"])
    ids = set()
    keys = set()
    for row in rows:
        for field in ("trace_id", "condition", "class", "question_id", "seed", "arrival_s",
                      "deadline_s", "prompt_sha256", "reference", "source", "exposure",
                      "scored", "initial_budget"):
            if field not in row:
                raise ValueError(f"missing {field} in {row.get('trace_id')}")
        if row["trace_id"] in ids:
            raise ValueError(f"duplicate trace_id {row['trace_id']}")
        ids.add(row["trace_id"])
        key = (row["class"], row["question_id"], row["seed"])
        if key in keys:
            raise ValueError(f"duplicate request key {key}")
        keys.add(key)
        q = questions.get(row["question_id"])
        if q is None:
            raise ValueError(f"unknown question {row['question_id']}")
        if hashlib.sha256(q["prompt"].encode()).hexdigest() != row["prompt_sha256"]:
            raise ValueError(f"prompt hash mismatch {row['question_id']}")
        if row["class"] == "signal" and row["question_id"] not in allowed_signal:
            raise ValueError(f"signal question outside the allowed cohort: {row['question_id']}")
        if row["class"] == "filler" and row["question_id"] not in set(cohort["filler_ids"]):
            raise ValueError(f"filler question outside filler pool: {row['question_id']}")
        if row["class"] == "filler" and row["scored"]:
            raise ValueError("filler must not be scored")
        if row["class"] == "signal" and not row["scored"]:
            raise ValueError("signal must be scored")
        if row["arrival_s"] < 0 or row["deadline_s"] <= 0:
            raise ValueError("invalid arrival or deadline")
    for previous, current in zip(rows, rows[1:]):
        if current["arrival_s"] < previous["arrival_s"]:
            raise ValueError("trace not sorted")
    return True


def trace_summary(rows):
    signal = [row for row in rows if row["class"] == "signal"]
    filler = [row for row in rows if row["class"] == "filler"]
    def q(values, p):
        values = sorted(values)
        return values[min(len(values) - 1, int(p * (len(values) - 1)))] if values else None
    arrivals = [row["arrival_s"] for row in rows]
    return {
        "requests": len(rows),
        "signal": len(signal),
        "filler": len(filler),
        "signal_questions": len({row["question_id"] for row in signal}),
        "seeds_per_question": (len(signal) / len({row["question_id"] for row in signal})
                               if signal else 0),
        "first_arrival_s": min(arrivals) if arrivals else None,
        "last_arrival_s": max(arrivals) if arrivals else None,
        "median_arrival_s": q(arrivals, 0.5),
        "p90_arrival_s": q(arrivals, 0.9),
        "span_s": (max(arrivals) - min(arrivals)) if arrivals else None,
    }


def write_trace(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


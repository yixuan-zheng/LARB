"""CPU-only completion audit, per-request metrics and paired summaries."""
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from . import config, grading, stats


def runtime_key(condition, arm, row):
    return f"{condition}--{arm}--{row['class']}--{row['question_id']}--{row['seed']}"


def _find_close(token_ids, close_id):
    return [i for i, token in enumerate(token_ids) if token == close_id]


def audit_completion(raw, cue_start=None):
    """Validate the realized thinking/cue/answer contract.

    Missing/partial/capped outcomes are failures, not exceptions.
    """
    if not raw:
        return dict(normal=False, reason="missing", complete=False, thinking_tokens=0,
                    answer_tokens=0, close_index=None, forced=False)
    token_ids = raw.get("token_ids") or []
    close_id = raw.get("close_id")
    eos_id = raw.get("eos_id")
    cue = raw.get("cue_ids") or []
    answer_cap = int(raw.get("answer_cap", 2048))
    complete = bool(raw.get("complete"))
    closes = _find_close(token_ids, close_id)
    if not complete or not token_ids:
        return dict(normal=False, reason="incomplete", complete=False, thinking_tokens=0,
                    answer_tokens=0, close_index=None, forced=False)
    if len(closes) != 1:
        return dict(normal=False, reason="bad_close_count", complete=True, thinking_tokens=0,
                    answer_tokens=0, close_index=None, forced=False)
    close = closes[0]
    if token_ids[-1] != eos_id:
        return dict(normal=False, reason="missing_eos", complete=True, thinking_tokens=0,
                    answer_tokens=0, close_index=close, forced=False)
    forced = False
    if cue_start is not None and cue:
        if token_ids[cue_start:cue_start + len(cue)] != cue:
            raise ValueError("realized cue does not match the frozen cue")
        forced = True
        thinking = cue_start
    else:
        thinking = close
    answer_tokens = len(token_ids) - close - 1
    # The controller forces EOS when the answer allowance is reached, so a cap
    # lands at exactly answer_cap tokens. `short_answer_closed` means the short
    # contract's closing brace+EOS were forced on an answer that finished
    # inside the allowance: that is a successful short answer, not a cap.
    flag = raw.get("capped")
    capped = (flag is True or flag == "answer_cap") or answer_tokens >= answer_cap
    return dict(normal=not capped, reason="answer_cap" if capped else "normal",
                complete=True, thinking_tokens=thinking, answer_tokens=answer_tokens,
                close_index=close, forced=forced)


def _phase_horizon(phase):
    if phase.get("horizon_s") is not None:
        return phase["horizon_s"]
    return phase["last_arrival_s"] + phase["deadline_s"] + phase.get("drain_allowance_s", 0)


def build_rows(trace_rows, phase, requests_by_key):
    """Build one row per planned trace request, including missing ones."""
    rows = []
    for trace in trace_rows:
        key = runtime_key(phase["condition"], phase["arm"], trace)
        raw = requests_by_key.get(key)
        scheduled = phase["epoch"] + trace["arrival_s"]
        deadline = scheduled + trace["deadline_s"]
        completion = audit_completion(raw, raw.get("cue_start") if raw else None)
        grade = grading.grade(raw.get("raw_output", "") if raw else "",
                              trace["reference"], use_math_verify=False)
        correct = bool(raw and completion["normal"] and grade["correct"])
        finish = raw.get("finished") if raw else None
        scheduler_start = raw.get("scheduler_start") if raw else None
        timely = bool(finish is not None and finish <= deadline and
                      finish <= phase["epoch"] + _phase_horizon(phase))
        queue_seconds = None
        service_seconds = None
        if raw and scheduler_start is not None:
            queue_seconds = max(0.0, scheduler_start - scheduled)
            service_seconds = max(0.0, finish - scheduler_start) if finish is not None else None
        rows.append({
            "phase": phase["name"], "condition": phase["condition"], "arm": phase["arm"],
            "key": key, "class": trace["class"], "question_id": trace["question_id"],
            "seed": trace["seed"], "scored": trace["scored"],
            "present": raw is not None, "complete": completion["complete"],
            "normal": completion["normal"], "reason": completion["reason"],
            "correct": correct, "timely": timely,
            "good": bool(trace["scored"] and correct and completion["normal"] and timely),
            "deadline": deadline, "finish": finish,
            "latency_seconds": (finish - scheduled) if finish is not None else None,
            "queue_seconds": queue_seconds, "service_seconds": service_seconds,
            "thinking_tokens": completion["thinking_tokens"],
            "answer_tokens": completion["answer_tokens"],
            "output_tokens": len(raw.get("token_ids", [])) if raw else 0,
            "cue_to_finish_seconds": (finish - raw.get("cue_start_time"))
            if raw and raw.get("cue_start_time") is not None and finish is not None else None,
            "initial_budget": raw.get("initial_budget") if raw else None,
            "final_budget": raw.get("final_budget") if raw else None,
            "cuts": len(raw.get("cut_events", [])) if raw else 0,
            "preemptions": raw.get("preemptions", 0) if raw else 0,
            "waiting_at_arrival": raw.get("waiting_at_arrival") if raw else None,
            "pressure_fraction": raw.get("pressure_fraction") if raw else None,
            "issue": grade["issue"] if raw else "missing",
            "extracted": grade["extracted"] if raw else None,
            "match": grade["match"] if raw else "missing",
        })
    return rows


def _q(values, p):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[min(len(values) - 1, int(p * (len(values) - 1)))]


def summarize_phase(rows, phase):
    scored = [row for row in rows if row["scored"]]
    n = len(scored)
    good = sum(row["good"] for row in scored)
    correct = sum(row["correct"] for row in scored)
    timely = sum(row["timely"] for row in scored)
    caps = sum(row["reason"] == "answer_cap" for row in scored)
    missing = sum(not row["present"] for row in scored)
    errors = sum(row["present"] and not row["complete"] for row in scored)
    horizon = _phase_horizon(phase)
    latencies = [r["latency_seconds"] for r in scored]
    queues = [r["queue_seconds"] for r in scored]
    return {
        "phase": phase["name"], "condition": phase["condition"], "arm": phase["arm"],
        "planned": n, "present": n - missing, "missing": missing, "errors": errors,
        "correct": correct, "correct_on_time": good, "timely": timely,
        "accuracy": correct / n if n else None,
        "on_time_rate": timely / n if n else None,
        "good_rate": good / n if n else None,
        "goodput_per_minute": 60 * good / horizon if horizon else None,
        "deadline_misses": n - timely, "caps": caps, "cap_rate": caps / n if n else None,
        "mean_latency_s": statistics.mean([v for v in latencies if v is not None])
        if any(v is not None for v in latencies) else None,
        "p50_latency_s": _q(latencies, 0.50),
        "p90_latency_s": _q(latencies, 0.90),
        "p99_latency_s": _q(latencies, 0.99),
        "mean_queue_s": statistics.mean([v for v in queues if v is not None])
        if any(v is not None for v in queues) else None,
        "total_output_tokens": sum(r["output_tokens"] for r in scored),
        "total_thinking_tokens": sum(r["thinking_tokens"] for r in scored),
        "total_answer_tokens": sum(r["answer_tokens"] for r in scored),
        "cuts": sum(r["cuts"] for r in scored),
        "preemptions": sum(r["preemptions"] for r in scored),
        "horizon_s": horizon,
    }


def question_means(rows):
    """Average the primary outcome over seeds within condition/arm/question."""
    grouped = defaultdict(list)
    for row in rows:
        if row["scored"]:
            grouped[(row["condition"], row["arm"], row["question_id"])].append(1.0 if row["good"] else 0.0)
    return {key: sum(values) / len(values) for key, values in grouped.items()}


def paired_table(rows, arm_a, arm_b):
    means = question_means(rows)
    pairs = []
    for (condition, arm, question_id), value in means.items():
        if arm != arm_a:
            continue
        other = means.get((condition, arm_b, question_id))
        if other is None:
            continue
        pairs.append({"condition": condition, "question_id": question_id,
                      "a": value, "b": other, "diff": value - other})
    return pairs


def paired_summary(pairs, resamples=10000, seed=20261113):
    if not pairs:
        return dict(n=0)
    by_condition = defaultdict(list)
    for pair in pairs:
        by_condition[pair["condition"]].append((pair["a"], pair["b"]))
    result = {"n": len(pairs)}
    for condition, values in sorted(by_condition.items()):
        result[condition] = stats.cluster_bootstrap(values, resamples=resamples, seed=seed)
        result[condition]["sign_test"] = stats.sign_test([a - b for a, b in values])
    pooled = [(pair["a"], pair["b"]) for pair in pairs]
    result["pooled"] = stats.cluster_bootstrap(pooled, resamples=resamples, seed=seed)
    result["pooled"]["sign_test"] = stats.sign_test([a - b for a, b in pooled])
    return result



def load_requests(run_dir):
    requests = {}
    folder = Path(run_dir) / "requests"
    if not folder.exists():
        return requests
    for path in sorted(folder.glob("*.json")):
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        requests[raw.get("key", path.stem)] = raw
    return requests


def _load_trace(phase, run_dir):
    if phase.get("trace_rows") is not None:
        return phase["trace_rows"]
    path = phase.get("trace_file")
    if path is None:
        raise ValueError(f"phase {phase.get('name')} has no trace")
    path = Path(path)
    if not path.is_absolute():
        path = Path(run_dir) / path
    rows = []
    with path.open() as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def analyze_run(run_dir, out_dir=None):
    run_dir = Path(run_dir)
    out_dir = Path(out_dir) if out_dir else run_dir / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    phase_file = run_dir / "phases.json"
    phases = json.loads(phase_file.read_text()) if phase_file.exists() else []
    requests = load_requests(run_dir)
    all_rows = []
    summaries = []
    for phase in phases:
        rows = build_rows(_load_trace(phase, run_dir), phase, requests)
        all_rows.extend(rows)
        summaries.append(summarize_phase(rows, phase))
    arms = sorted({phase["arm"] for phase in phases})
    paired = {}
    for index, arm_a in enumerate(arms):
        for arm_b in arms[index + 1:]:
            pairs = paired_table(all_rows, arm_a, arm_b)
            if pairs:
                paired[f"{arm_a}_vs_{arm_b}"] = {"pairs": pairs,
                                                  "summary": paired_summary(pairs)}
    result = {
        "run_dir": str(run_dir),
        "phases": summaries,
        "paired": paired,
        "rows": all_rows,
        "review_queue": [row for row in all_rows
                         if row["scored"] and (row["issue"] or not row["correct"])],
        "caveats": [
            "Caps, missing outputs and late answers remain failures.",
            "Paired summaries resample questions, not responses.",
            "A phase missing coverage is not a policy result.",
        ],
    }
    config.write_json(out_dir / "analysis.json", result)
    with (out_dir / "paired.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["comparison", "condition", "question_id", "a", "b", "diff"])
        for name, block in paired.items():
            for pair in block["pairs"]:
                writer.writerow([name, pair["condition"], pair["question_id"],
                                 pair["a"], pair["b"], pair["diff"]])
    config.write_json(out_dir / "review-queue.json", result["review_queue"])
    config.write_json(out_dir / "summary.json", summaries)
    return result


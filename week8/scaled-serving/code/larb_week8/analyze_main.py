"""Safe analysis of a completed P2 main run.

The week 7 analyzer grades with exact match only.  This module builds the same
per-request rows but uses the Week 8 safe normalised grader, then reuses the
week 7 paired bootstrap and phase summaries.  It is CPU-only and does not
touch the GPU.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from larb_week8 import audit, config
from larb_scaled import analysis


def load_phases(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / "phases.json"
    if path.exists():
        phases = json.loads(path.read_text())
        if phases:
            return phases
    return [json.loads(item.read_text())
            for item in sorted((Path(run_dir) / "phases").glob("*.json"))]


def build_rows(run_dir: Path) -> tuple[list[dict], list[dict]]:
    run_dir = Path(run_dir)
    phases = load_phases(run_dir)
    requests = analysis.load_requests(run_dir)
    clients = {}
    for phase in phases:
        for client in phase.get("client_records", []):
            clients[client["key"]] = client
    all_rows = []
    for phase in phases:
        trace_path = Path(phase["trace_file"])
        trace_rows = [json.loads(line) for line in trace_path.read_text().splitlines()
                      if line.strip()]
        rows = []
        for trace in trace_rows:
            key = analysis.runtime_key(phase["condition"], phase["arm"], trace)
            raw = requests.get(key)
            client = clients.get(key, {})
            submitted = client.get("client_submitted", phase["epoch"] + trace["arrival_s"])
            deadline = submitted + trace["deadline_s"]
            if raw:
                grade = audit.grade_record(raw, "normalized_safe")
                completion = {
                    "normal": grade["normal"], "reason": grade["reason"],
                    "thinking_tokens": grade["thinking_tokens"],
                    "answer_tokens": grade["answer_tokens"], "complete": grade["complete"],
                }
            else:
                grade = {"correct": False, "normal": False, "reason": "missing",
                         "extracted": None, "issue": "missing", "match": "missing"}
                completion = {"normal": False, "reason": "missing", "thinking_tokens": 0,
                              "answer_tokens": 0, "complete": False}
            finish = raw.get("finished") if raw else None
            scheduler_start = raw.get("scheduler_start") if raw else None
            latency = (finish - submitted) if finish is not None else None
            timely = bool(latency is not None and latency <= trace["deadline_s"])
            correct = bool(raw and completion["normal"] and grade["correct"])
            rows.append({
                "phase": phase["name"], "condition": phase["condition"], "arm": phase["arm"],
                "key": key, "class": trace["class"], "question_id": trace["question_id"],
                "seed": trace["seed"], "scored": trace["scored"],
                "present": raw is not None, "complete": completion["complete"],
                "normal": completion["normal"], "reason": completion["reason"],
                "correct": correct, "timely": timely,
                "good": bool(trace["scored"] and correct and completion["normal"] and timely),
                "deadline": deadline, "finish": finish, "latency_seconds": latency,
                "queue_seconds": (max(0.0, scheduler_start - submitted)
                                  if scheduler_start is not None else None),
                "service_seconds": (max(0.0, finish - scheduler_start)
                                    if finish is not None and scheduler_start is not None else None),
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
        all_rows.extend(rows)
    return all_rows, phases


def analyse(run_dir: Path, out_dir: Path | None = None) -> dict:
    run_dir = Path(run_dir)
    out_dir = Path(out_dir or run_dir / "analysis")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, phases = build_rows(run_dir)
    by_phase = defaultdict(list)
    for row in rows:
        by_phase[row["phase"]].append(row)
    summaries = [analysis.summarize_phase(by_phase[phase["name"]], phase)
                 for phase in phases]
    arms = sorted({row["arm"] for row in rows})
    paired = {}
    primary_rows = [row for row in rows if row["condition"] in ("sustained", "burst")]
    for index, arm_a in enumerate(arms):
        for arm_b in arms[index + 1:]:
            pairs = analysis.paired_table(primary_rows, arm_a, arm_b)
            if pairs:
                paired[f"{arm_a}_vs_{arm_b}"] = {
                    "pairs": pairs, "summary": analysis.paired_summary(pairs)}
    result = {
        "run_dir": str(run_dir),
        "grader": "normalized_safe",
        "phases": summaries,
        "paired_primary_pressure": paired,
        "rows": rows,
        "review_queue": [row for row in rows if row["scored"] and
                         (row["issue"] or not row["correct"])],
        "caveats": [
            "Caps, missing outputs and late answers remain failures.",
            "Paired summaries resample questions, not responses.",
            "The primary comparison excludes the low-load control.",
            "The realised seed count is read from the frozen packet, not from this file.",
        ],
    }
    config.write_json(out_dir / "analysis.json", result)
    config.write_json(out_dir / "summary.json", summaries)
    config.write_json(out_dir / "review-queue.json", result["review_queue"])
    with (out_dir / "paired.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["comparison", "condition", "question_id", "a", "b", "diff"])
        for name, block in paired.items():
            for pair in block["pairs"]:
                writer.writerow([name, pair["condition"], pair["question_id"],
                                 pair["a"], pair["b"], pair["diff"]])
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    analyse(args.run, args.out)


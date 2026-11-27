"""Analyse the Week 8 240 s calibration with the corrections the P1 review found.

Corrections relative to the P1 summariser:
* pressure uses the actual threshold (8 of 32), not the protocol minimum (4);
* arrivals before the warm-up window are excluded from the miss rate, while
  their requests still warm the queue;
* latency and timeliness are measured from actual client submission, not the
  scheduled trace offset;
* every phase is filtered by its own request-key prefix.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from larb_week8 import config
from larb_scaled import analysis


def load_phases(run_dir: Path) -> list[dict]:
    run_dir = Path(run_dir)
    path = run_dir / "phases.json"
    if path.exists():
        phases = json.loads(path.read_text())
        if phases:
            return phases
    return [json.loads(item.read_text()) for item in sorted((run_dir / "phases").glob("*.json"))]


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not Path(path).exists():
        return rows
    with Path(path).open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def _q(values, fraction):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[min(len(values) - 1, int(fraction * (len(values) - 1)))]


def phase_metrics(run_dir: Path, phase: dict, deadline: float,
                  warmup_s: float, threshold: int = 8) -> dict:
    run_dir = Path(run_dir)
    prefix = f"{phase['condition']}--{phase['arm']}--"
    requests = analysis.load_requests(run_dir)
    clients = phase.get("client_records", [])
    measured = []
    for client in clients:
        arrival_offset = float(client.get("scheduled", phase["epoch"])) - phase["epoch"]
        client["_arrival_offset"] = arrival_offset
        if arrival_offset >= warmup_s:
            measured.append(client)
    signal = [row for row in measured if row["class"] == "signal"]
    measured_keys = {row["key"] for row in signal}
    misses = []
    latencies = []
    for row in signal:
        finish = row.get("server_finished")
        submitted = row.get("client_submitted")
        if finish is None or submitted is None:
            misses.append(row)
            latencies.append(None)
            continue
        latency = finish - submitted
        latencies.append(latency)
        if latency > deadline:
            misses.append(row)
    service = []
    cut_after_close = 0
    preemptions = []
    for row in signal:
        raw = requests.get(row["key"])
        if not raw:
            continue
        if raw.get("scheduler_start") is not None and raw.get("finished") is not None:
            service.append(raw["finished"] - raw["scheduler_start"])
        preemptions.append(raw.get("preemptions") or 0)
        cue_start = raw.get("cue_start")
        for cut in raw.get("cut_events") or []:
            # A cut at exactly cue_start is the boundary cut that triggered the
            # cue: RequestControl.change() rejects cuts once force_start is set,
            # so a same-position cut is before the cue, not after it.  Only a
            # cut strictly beyond the cue is after close.
            if cue_start is not None and cut.get("tokens", 0) > cue_start:
                cut_after_close += 1
    scheduler = [row for row in load_jsonl(run_dir / "scheduler.jsonl")
                 if row.get("event") == "step"]
    waiting, running, pressure, pressure4 = [], [], 0, 0
    for row in scheduler:
        keys = list(row.get("waiting", []))
        active = [entry.get("key") for entry in row.get("active", [])]
        if not any(str(key).startswith(prefix) for key in keys + active):
            continue
        if row.get("monotonic") is not None:
            if float(row["monotonic"]) - phase["epoch"] < warmup_s:
                continue
        phase_waiting = [key for key in keys if str(key).startswith(prefix)]
        waiting.append(len(phase_waiting))
        running.append(int(row.get("running_count") or 0))
        if len(phase_waiting) >= threshold:
            pressure += 1
        if len(phase_waiting) >= 4:
            pressure4 += 1
    worker_cuts = [row for row in load_jsonl(run_dir / "worker.jsonl")
                   if row.get("event") == "live_reduction"
                   and str(row.get("key", "")).startswith(prefix)]
    budgets = [requests[key].get("initial_budget") for key in measured_keys
               if key in requests and requests[key].get("scored")]
    n = len(signal)
    return {
        "phase": phase["name"], "condition": phase["condition"], "arm": phase["arm"],
        "measured_signal": n,
        "signal_miss": len(misses),
        "signal_miss_rate": (len(misses) / n) if n else None,
        "signal_latency_p50": _q(latencies, 0.50),
        "signal_latency_p90": _q(latencies, 0.90),
        "service_p50": _q(service, 0.50),
        "service_p90": _q(service, 0.90),
        "request_errors": phase.get("errors"),
        "injection_valid": phase.get("injection_valid"),
        "max_injection_lag_seconds": phase.get("max_injection_lag_seconds"),
        "scheduler_samples": len(waiting),
        "pressure_fraction": (pressure / len(waiting)) if waiting else None,
        "pressure_fraction_threshold4": (pressure4 / len(waiting)) if waiting else None,
        "waiting_mean": statistics.mean(waiting) if waiting else None,
        "waiting_p90": _q(waiting, 0.90),
        "waiting_max": max(waiting) if waiting else None,
        "running_mean": statistics.mean(running) if running else None,
        "preemptions_mean": statistics.mean(preemptions) if preemptions else None,
        "preemptions_max": max(preemptions) if preemptions else None,
        "cuts": len(worker_cuts),
        "cut_requests": len({row.get("key") for row in worker_cuts}),
        "cut_after_close": cut_after_close,
        "admission_budget_short": sum(1 for value in budgets if value == 4096),
        "admission_budget_long": sum(1 for value in budgets if value == 8192),
        "admission_total": len(budgets),
    }


def summarise(run_dir: Path, deadline: float, warmup_s: float,
              threshold: int = 8) -> dict:
    run_dir = Path(run_dir)
    phases = load_phases(run_dir)
    rates = []
    for phase in phases:
        if phase["arm"] != "fixed8k":
            continue
        rates.append(phase_metrics(run_dir, phase, deadline, warmup_s, threshold))
    rates.sort(key=lambda row: _rate_of(row) or 0.0)
    band = [0.15, 0.40]
    candidates = [row for row in rates if row.get("signal_miss_rate") is not None]
    inside = [row for row in candidates if band[0] <= row["signal_miss_rate"] <= band[1]]
    chosen = None
    if inside:
        chosen = min(inside, key=lambda row: abs(row["signal_miss_rate"] - 0.25))
    below = [row for row in candidates if row["signal_miss_rate"] < band[0]]
    above = [row for row in candidates if row["signal_miss_rate"] > band[1]]
    bracket = None
    if below and above:
        low = max(below, key=lambda row: row["signal_miss_rate"])
        high = min(above, key=lambda row: row["signal_miss_rate"])
        bracket = {"below": low, "above": high}
    return {
        "generated_at": config.utc_now(),
        "run_dir": str(run_dir),
        "deadline_seconds": deadline,
        "warmup_seconds": warmup_s,
        "threshold": threshold,
        "band": band,
        "target_miss_rate": 0.25,
        "rates": rates,
        "rates_in_band": [row["phase"] for row in inside],
        "chosen": chosen["phase"] if chosen else None,
        "chosen_rate_per_hour": _rate_of(chosen) if chosen else None,
        "chosen_miss_rate": chosen["signal_miss_rate"] if chosen else None,
        "bracket": bracket,
        "band_found": bool(chosen),
        "note": ("Choose this rate and freeze the main trace."
                 if chosen else
                 "No rate produced a 15-40% measured miss rate; run the pre-declared refinement grid or stop."),
    }


def _rate_of(row: dict):
    if not row:
        return None
    try:
        return float(str(row["condition"]).rsplit("-", 1)[-1])
    except ValueError:
        return None


def live_check(run_dir: Path, deadline: float, warmup_s: float,
               threshold: int = 8) -> dict:
    run_dir = Path(run_dir)
    phases = load_phases(run_dir)
    live = [phase for phase in phases if phase["arm"] == "live"]
    if not live:
        return {"present": False, "pass": False,
                "note": "No live manipulation phase was run."}
    metrics = [phase_metrics(run_dir, phase, deadline, warmup_s, threshold)
               for phase in live]
    cuts = sum(item["cuts"] for item in metrics)
    cut_requests = sum(item["cut_requests"] for item in metrics)
    cut_after_close = sum(item["cut_after_close"] for item in metrics)
    pressure = max((item["pressure_fraction"] or 0.0) for item in metrics)
    admission_short = sum(item["admission_budget_short"] for item in metrics)
    admission_long = sum(item["admission_budget_long"] for item in metrics)
    passed = bool(cuts > 0 and cut_requests > 0 and cut_after_close == 0
                  and pressure > 0 and admission_short > 0 and admission_long > 0)
    return {
        "present": True,
        "pass": passed,
        "cuts": cuts,
        "cut_requests": cut_requests,
        "cut_after_close": cut_after_close,
        "pressure_fraction": pressure,
        "admission_short": admission_short,
        "admission_long": admission_long,
        "metrics": metrics,
        "note": ("The live mechanism fired in flight and the admission rule produced both budgets."
                 if passed else
                 "The live manipulation check failed; do not treat the calibration as a valid live test."),
    }



def write_markdown(result: dict, path: Path) -> None:
    lines = ["# Week 8 calibration", "",
             f"Generated: {result['generated_at']}", "",
             f"Deadline: {result['deadline_seconds']:.0f} s; warm-up: "
             f"{result['warmup_seconds']:.0f} s; pressure threshold: {result['threshold']}", "",
             "## Rates", "",
             "| phase | measured signal | misses | miss rate | p50 latency | p90 latency | service p90 | pressure >=8 | waiting p90 | running mean | cuts |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in result["rates"]:
        lines.append(
            f"| {row['phase']} | {row['measured_signal']} | {row['signal_miss']} | "
            f"{row['signal_miss_rate']:.3f} | {row['signal_latency_p50']:.1f} | "
            f"{row['signal_latency_p90']:.1f} | {row['service_p90']:.1f} | "
            f"{row['pressure_fraction']:.3f} | {row['waiting_p90']} | "
            f"{row['running_mean']:.1f} | {row['cuts']} |")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    lines.append(f"Band: {result['band']}; rates in band: `{result['rates_in_band']}`")
    lines.append("")
    lines.append(f"Chosen: `{result['chosen']}` at "
                 f"{result['chosen_rate_per_hour']} per hour "
                 f"(miss rate {result['chosen_miss_rate']})")
    lines.append("")
    lines.append(result["note"])
    lines.append("")
    Path(path).write_text("\n".join(lines) + "\n")


def main(run_dir: Path, out_dir: Path | None = None,
         deadline: float | None = None, warmup_s: float | None = None,
         threshold: int = 8) -> dict:
    qualify = config.load_qualify()["calibration"]
    deadline = float(deadline or qualify["deadline_seconds"])
    warmup_s = float(warmup_s if warmup_s is not None else qualify["warmup_seconds"])
    out_dir = Path(out_dir or config.RESULTS_DIR)
    result = summarise(run_dir, deadline, warmup_s, threshold)
    live = live_check(run_dir, deadline, warmup_s, threshold)
    result["live_check"] = live
    out = out_dir / "calibration.json"
    report = out_dir / "CALIBRATION.md"
    config.write_json(out, result)
    write_markdown(result, report)
    print(json.dumps({"out": str(out), "report": str(report),
                      "band_found": result["band_found"],
                      "chosen": result["chosen"],
                      "chosen_rate_per_hour": result["chosen_rate_per_hour"],
                      "live_check": live.get("pass")}, indent=2))
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--deadline", type=float)
    parser.add_argument("--warmup", type=float)
    parser.add_argument("--threshold", type=int, default=8)
    args = parser.parse_args()
    main(args.run, args.out, args.deadline, args.warmup, args.threshold)


#!/usr/bin/env python3
"""P1 Gate F: load and deadline calibration, plus the live manipulation check.

The arrival rate is a calibration output, not a hypothesis parameter. Each
point replays a seeded Poisson trace of the 48 screening questions plus 30%
filler through the fixed8k reference arm at a 180 s deadline; the point whose
signal miss rate falls in 15-40% (target 20-30%) is chosen and frozen.

Usage:
  calibrate_load.py --stage rates --out results/p1/calibration
  calibrate_load.py --stage live --out results/p1/calibration --rate 900
  calibrate_load.py --stage summarize --out results/p1/calibration
"""
import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from larb_scaled import config, runner, workload  # noqa: E402


def build_rate_trace(name, path, cohort, questions, protocol, rate_per_hour,
                     duration_s, deadline_s, seed, filler_share=0.30):
    signal_ids = list(cohort["screen_ids"])
    filler_ids = list(cohort["filler_ids"])
    total = max(2, int(round(rate_per_hour * duration_s / 3600.0)))
    signal_n = int(round(total * (1 - filler_share)))
    filler_n = total - signal_n
    base = protocol["seeding"]["seed_base"]
    rows = []
    for index in range(signal_n):
        qid = signal_ids[index % len(signal_ids)]
        q = questions[qid]
        rows.append({"class": "signal", "question_id": qid, "seed": base + 900000 + index,
                     "prompt_sha256": q["prompt_sha256"], "reference": q["answer"],
                     "source": q["pool"], "exposure": q["exposure"],
                     "answer_type": q["answer_type"], "scored": True,
                     "initial_budget": None})
    for index in range(filler_n):
        qid = filler_ids[index % len(filler_ids)]
        q = questions[qid]
        rows.append({"class": "filler", "question_id": qid, "seed": base + 950000 + index,
                     "prompt_sha256": q["prompt_sha256"], "reference": q["answer"],
                     "source": q["pool"], "exposure": q["exposure"],
                     "answer_type": q["answer_type"], "scored": False,
                     "initial_budget": protocol["workload"]["filler_budget"]})
    rng = random.Random(f"{name}:{seed}")
    rate = rate_per_hour / 3600.0
    times = []
    clock = 0.0
    for _ in rows:
        clock += rng.expovariate(rate)
        times.append(clock)
    order = list(range(len(rows)))
    rng.shuffle(order)
    for slot, index in enumerate(order):
        rows[index]["arrival_s"] = round(times[slot], 6)
    for row in rows:
        row["condition"] = name
        row["deadline_s"] = deadline_s
        row["trace_id"] = f"{name}--{row['class']}--{row['question_id']}--{row['seed']}"
    rows.sort(key=lambda row: (row["arrival_s"], row["trace_id"]))
    workload.validate_trace(rows, name, protocol, cohort, questions,
                           allowed_signal_ids=signal_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    sha = workload.write_trace(path, rows)
    return rows, sha



def read_jsonl(path):
    rows = []
    path = Path(path)
    if not path.exists():
        return rows
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def phase_metrics(run_dir, phase_record):
    condition = phase_record["condition"]
    threshold = config.load_protocol()["policy"]["pressure"]["threshold_minimum"]
    clients = phase_record.get("client_records", [])
    signal = [row for row in clients if row["class"] == "signal"]
    misses = [row for row in signal if not row.get("timely")]
    scheduler = [row for row in read_jsonl(Path(run_dir) / "scheduler.jsonl")
                 if row.get("event") == "step"]
    prefix = f"{condition}--"
    waiting = []
    running = []
    under_pressure = 0
    active_samples = 0
    for row in scheduler:
        keys = list(row.get("waiting", []))
        active_keys = [entry.get("key") for entry in row.get("active", [])]
        # Only samples where this phase is live count; later phases append to
        # the same file and would otherwise dilute the fraction.
        if not any(str(key).startswith(prefix) for key in keys + active_keys):
            continue
        active_samples += 1
        phase_waiting = [key for key in keys if str(key).startswith(prefix)]
        waiting.append(len(phase_waiting))
        running.append(int(row.get("running_count") or 0))
        if len(phase_waiting) >= threshold:
            under_pressure += 1
    cuts = [row for row in read_jsonl(Path(run_dir) / "worker.jsonl")
            if row.get("event") == "live_reduction"
            and str(row.get("key", "")).startswith(f"{condition}--")]
    requests = {}
    request_dir = Path(run_dir) / "requests"
    if request_dir.exists():
        for path in request_dir.glob(f"{condition}--*.json"):
            try:
                requests[path.stem] = json.loads(path.read_text())
            except json.JSONDecodeError:
                pass
    budgets = [row.get("initial_budget") for row in requests.values()
               if row.get("scored")]

    def q(values, fraction):
        values = sorted(v for v in values if v is not None)
        return values[min(len(values) - 1, int(fraction * (len(values) - 1)))] if values else None

    return dict(
        phase=phase_record["name"], condition=condition, arm=phase_record["arm"],
        signal=len(signal), signal_miss=len(misses),
        signal_miss_rate=(len(misses) / len(signal)) if signal else None,
        signal_latency_p50=q([r.get("latency_seconds") for r in signal], 0.50),
        signal_latency_p90=q([r.get("latency_seconds") for r in signal], 0.90),
        request_errors=phase_record.get("errors"),
        injection_valid=phase_record.get("injection_valid"),
        max_injection_lag_seconds=phase_record.get("max_injection_lag_seconds"),
        scheduler_samples=active_samples,
        pressure_fraction=(under_pressure / active_samples) if active_samples else None,
        waiting_mean=(statistics.mean(waiting) if waiting else None),
        waiting_p90=q(waiting, 0.90), waiting_max=max(waiting) if waiting else None,
        running_mean=(statistics.mean(running) if running else None),
        cuts=len(cuts), cut_requests=len({row.get("key") for row in cuts}),
        cut_tokens_median=q([row.get("tokens") for row in cuts], 0.50),
        admission_budget_short=sum(1 for value in budgets if value == 4096),
        admission_budget_long=sum(1 for value in budgets if value == 8192),
        admission_total=len(budgets),
    )


def collect(run_dir):
    path = Path(run_dir) / "phases.json"
    if not path.exists():
        return []
    return [phase_metrics(run_dir, record) for record in json.loads(path.read_text())]



def build_burst_trace(name, path, cohort, questions, protocol, baseline_rate, duration_s,
                      burst_count, burst_start_s, burst_spacing_s, deadline_s, seed,
                      filler_share=0.30):
    """Baseline Poisson arrivals plus one scripted burst, like the main burst trace."""
    signal_ids = list(cohort["screen_ids"])
    filler_ids = list(cohort["filler_ids"])
    base_total = max(2, int(round(baseline_rate * duration_s / 3600.0)))
    total = base_total + burst_count
    signal_n = int(round(total * (1 - filler_share)))
    filler_n = total - signal_n
    base = protocol["seeding"]["seed_base"]
    rows = []
    for index in range(signal_n):
        qid = signal_ids[index % len(signal_ids)]
        q = questions[qid]
        rows.append({"class": "signal", "question_id": qid, "seed": base + 960000 + index,
                     "prompt_sha256": q["prompt_sha256"], "reference": q["answer"],
                     "source": q["pool"], "exposure": q["exposure"],
                     "answer_type": q["answer_type"], "scored": True,
                     "initial_budget": None})
    for index in range(filler_n):
        qid = filler_ids[index % len(filler_ids)]
        q = questions[qid]
        rows.append({"class": "filler", "question_id": qid, "seed": base + 980000 + index,
                     "prompt_sha256": q["prompt_sha256"], "reference": q["answer"],
                     "source": q["pool"], "exposure": q["exposure"],
                     "answer_type": q["answer_type"], "scored": False,
                     "initial_budget": protocol["workload"]["filler_budget"]})
    rng = random.Random(f"{name}:{seed}")
    rate = baseline_rate / 3600.0
    times = []
    for _ in range(base_total):
        times.append(rng.expovariate(rate) + times[-1] if times else rng.expovariate(rate))
    times.extend(burst_start_s + index * burst_spacing_s for index in range(burst_count))
    times = times[:len(rows)]
    order = list(range(len(rows)))
    rng.shuffle(order)
    for slot, index in enumerate(order):
        rows[index]["arrival_s"] = round(times[slot], 6)
    for row in rows:
        row["condition"] = name
        row["deadline_s"] = deadline_s
        row["trace_id"] = f"{name}--{row['class']}--{row['question_id']}--{row['seed']}"
    rows.sort(key=lambda row: (row["arrival_s"], row["trace_id"]))
    workload.validate_trace(rows, name, protocol, cohort, questions,
                           allowed_signal_ids=signal_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    sha = workload.write_trace(path, rows)
    return rows, sha


def derive_rates(sweep_path, factors=(0.6, 0.75, 0.9), tokens_per_request=4500.0):
    """Candidate arrival rates around the measured capacity.

    Capacity (requests/hour) = output tokens/s * 3600 / mean tokens per
    request. The mean uses 6k for signal requests and about 1.1k for the 30%
    filler share, i.e. roughly 4.5k tokens per request.
    """
    path = Path(sweep_path)
    if not path.exists():
        return None, None
    sweep = json.loads(path.read_text())
    recommendation = sweep.get("recommendation") or {}
    rate = recommendation.get("rate_arm_average")
    if not rate:
        return None, None
    capacity = rate * 3600.0 / tokens_per_request
    rates = [int(round(factor * capacity)) for factor in factors]
    return sorted(set(max(100, value) for value in rates)), dict(
        basis="gate C rate_arm_average", tokens_per_second=rate,
        tokens_per_request=tokens_per_request, capacity_per_hour=capacity,
        factors=list(factors))


def summarize(out):
    rates_dir = Path(out) / "rates"
    live_dir = Path(out) / "live"
    rates = collect(rates_dir)
    live = collect(live_dir)
    plan = {}
    for name in ("rates", "live"):
        path = Path(out) / name / "plan.json"
        if path.exists():
            plan[name] = json.loads(path.read_text())
    candidates = [row for row in rates if row.get("signal_miss_rate") is not None]
    band = (0.15, 0.40)
    inside = [row for row in candidates if band[0] <= row["signal_miss_rate"] <= band[1]]
    chosen = None
    if inside:
        chosen = min(inside, key=lambda row: abs(row["signal_miss_rate"] - 0.25))
    decision = dict(
        generated_at=config.utc_now(),
        rates=rates, live=live, plan=plan,
        band=list(band),
        rates_in_band=[row["phase"] for row in inside],
        chosen=(chosen["phase"] if chosen else None),
        chosen_rate_per_hour=(float(chosen["condition"].rsplit("-", 1)[-1])
                              if chosen else None),
        chosen_miss_rate=(chosen["signal_miss_rate"] if chosen else None),
        live_check=dict(
            cuts=sum(row["cuts"] for row in live),
            cut_requests=sum(row["cut_requests"] for row in live),
            pressure_fraction=(live[0]["pressure_fraction"] if live else None),
            admission_short=sum(row["admission_budget_short"] for row in live),
            admission_long=sum(row["admission_budget_long"] for row in live),
            miss_rate=(live[0]["signal_miss_rate"] if live else None),
        ),
        note=("Choose this rate, keep the 180 s deadline and freeze the trace."
              if chosen else
              "No rate produced a 15-40% reference miss rate; revise the SLO to 240 s "
              "and repeat calibration before the main run."),
    )
    config.write_json(Path(out) / "calibration.json", decision)
    print(json.dumps({key: decision[key] for key in
                      ("chosen", "chosen_rate_per_hour", "chosen_miss_rate",
                       "rates_in_band", "note")}, indent=2))
    return decision


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["rates", "live", "burst", "summarize"], required=True)
    parser.add_argument("--arm", default="live", choices=["live", "arrival", "fixed8k", "fixed4k"])
    parser.add_argument("--burst-count", type=int, default=60)
    parser.add_argument("--burst-start", type=float, default=300.0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rates", type=float, nargs="+")
    parser.add_argument("--minutes", type=float, default=20.0)
    parser.add_argument("--live-minutes", type=float, default=30.0)
    parser.add_argument("--rate", type=float)
    parser.add_argument("--threshold", type=int, default=8)
    parser.add_argument("--max-num-seqs", type=int, default=32)
    parser.add_argument("--deadline", type=float, default=None,
                        help="declared SLO in seconds (default: protocol 180; 240 is the fallback)")
    parser.add_argument("--seed", type=int, default=20261113)
    parser.add_argument("--graph", action="store_true",
                        help="use CUDA graphs (only after Gate B passes)")
    parser.add_argument("--sweep", type=Path,
                        default=ROOT / "results/p1/sweep/throughput.json",
                        help="Gate C result used to derive the rate grid")
    args = parser.parse_args()
    if args.stage == "summarize":
        summarize(args.out)
        return
    protocol = config.load_protocol()
    cohort = config.load_cohort()
    questions = workload.load_questions()
    deadline = float(args.deadline or protocol["deadline"]["slo_seconds"])
    run_dir = args.out / args.stage
    trace_dir = args.out / "traces"
    if args.stage == "burst":
        if not args.rate:
            raise SystemExit("--rate is required for the burst stage")
        name = f"gate-burstcal-{int(args.rate)}-{args.arm}"
        run_dir = args.out / "burst" / args.arm
        path = trace_dir / f"{name}.jsonl"
        rows, sha = build_burst_trace(
            name, path, cohort, questions, protocol, baseline_rate=args.rate,
            duration_s=args.minutes * 60.0, burst_count=args.burst_count,
            burst_start_s=args.burst_start, burst_spacing_s=0.5,
            deadline_s=deadline, seed=args.seed)
        phases = [runner.make_phase(
            name, name, args.arm, path, deadline_s=deadline, drain_allowance_s=300.0,
            contract="legacy", enforce_eager=not args.graph,
            env={"LARB_THRESHOLD": args.threshold, "LARB_MAX_NUM_SEQS": args.max_num_seqs})]
        run_dir.mkdir(parents=True, exist_ok=True)
        config.write_json(run_dir / "plan.json", phases)
        manifest = {"stage": "burst", "arm": args.arm, "rate_per_hour": args.rate,
                    "threshold": args.threshold, "minutes": args.minutes,
                    "burst_count": args.burst_count, "burst_start_s": args.burst_start,
                    "deadline_s": deadline, "enforce_eager": not args.graph,
                    "trace": {"file": str(path), "sha256": sha, "requests": len(rows)}}
        config.write_json(run_dir / "calibration-manifest.json", manifest)
        records = runner.run_sequence(phases, run_dir)
        metrics = collect(run_dir)
        config.write_json(run_dir / "metrics.json",
                          {"phases": metrics, "manifest": manifest,
                           "invalid": [r["name"] for r in records
                                       if not r.get("injection_valid", True)]})
        print(json.dumps(metrics, indent=2))
        return
    if args.stage == "rates":
        derived, basis = derive_rates(args.sweep)
        rate_list = args.rates or derived or config.load_p1_gates()["gates"]["calibration"]["rates_per_hour"]
        minutes = args.minutes
        arm = "fixed8k"
        rate_basis = basis or {"basis": "p1_gates.json candidate grid"}
    else:
        if not args.rate:
            raise SystemExit("--rate is required for the live stage")
        rate_list = [args.rate]
        minutes = args.live_minutes
        arm = "live"
        rate_basis = {"basis": "chosen by the rate stage"}
    phases = []
    manifest = {"stage": args.stage, "arm": arm, "threshold": args.threshold,
                "minutes": minutes, "deadline_s": deadline,
                "enforce_eager": not args.graph, "rate_basis": rate_basis,
                "traces": {}}
    for rate in rate_list:
        name = f"gate-cal-{int(rate)}" if args.stage == "rates" else f"gate-live-{int(rate)}"
        path = trace_dir / f"{name}.jsonl"
        rows, sha = build_rate_trace(name, path, cohort, questions, protocol, rate,
                                     minutes * 60.0, deadline, args.seed)
        manifest["traces"][name] = {"file": str(path), "sha256": sha,
                                    "requests": len(rows), "rate_per_hour": rate,
                                    "signal": sum(1 for row in rows
                                                  if row["class"] == "signal")}
        phases.append(runner.make_phase(
            name, name, arm, path, deadline_s=deadline, drain_allowance_s=300.0,
            contract="legacy", enforce_eager=not args.graph,
            env={"LARB_THRESHOLD": args.threshold, "LARB_MAX_NUM_SEQS": args.max_num_seqs}))
    run_dir.mkdir(parents=True, exist_ok=True)
    config.write_json(run_dir / "plan.json", phases)
    config.write_json(run_dir / "calibration-manifest.json", manifest)
    records = runner.run_sequence(phases, run_dir)
    invalid = [record["name"] for record in records if not record.get("injection_valid", True)]
    metrics = collect(run_dir)
    config.write_json(run_dir / "metrics.json", {"phases": metrics, "invalid": invalid})
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

"""P2C quality-first burst pilot.

This is a new pre-declaration (``configs/p2c_burst_pilot.json``), not a change
to the closed P2B calibration.  It replays a short slack -> burst -> recovery
trace on the frozen rig, grades AIME quality with the safe normaliser, and
applies the pre-declared validity / slope / non-inferiority screens.

CPU-only except ``run``; the GPU execution reuses the frozen week 7 runner.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from larb_week8 import audit, calibrate, candidate, config, runner
from larb_scaled import analysis, stats, workload

CONFIG_PATH = config.CONFIG_DIR / "p2c_burst_pilot.json"
PREFILL_CONFIG_PATH = config.CONFIG_DIR / "p3c_prefill.json"
TRACE_DIR = config.ARTIFACTS_DIR / "traces-candidates"
ARMS = ("fixed4k", "fixed8k", "arrival", "live")


def load_config() -> dict:
    return config.read_json(CONFIG_PATH)


def trace_specs(which: str = "both", cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_config()
    specs = list(cfg["design"]["traces"])
    if which == "a":
        return [spec for spec in specs if spec["name"].endswith("-a")]
    if which == "b":
        return [spec for spec in specs if spec["name"].endswith("-b")]
    if which != "both":
        raise ValueError(which)
    return specs


def _protocol(spec: dict, cfg: dict) -> dict:
    protocol = candidate.protocol(seeds=int(cfg["design"]["seeds_per_question_per_trace"]))
    protocol["name"] = "p2c-burst"
    protocol["seeding"] = {"seed_base": int(spec["seed_base"]),
                           "question_stride": 17, "seed_stride": 1}
    protocol["workload"]["filler_share"] = float(cfg["pool"]["filler_share"])
    protocol["workload"]["conditions"]["burst"].update({
        "provisional_baseline_per_hour": float(spec["baseline_rate_per_hour"]),
        "burst_start_s": float(spec["burst_start_s"]),
        "burst_count": int(spec["burst_count"]),
        "burst_spacing_s": float(spec["burst_spacing_s"]),
        "recovery_rate_per_hour": float(spec["recovery_rate_per_hour"]),
        "signal_questions": int(cfg["pool"]["questions"]),
        "seeds": int(cfg["design"]["seeds_per_question_per_trace"]),
    })
    return protocol


def build_trace(spec: dict, cfg: dict | None = None,
                trace_dir: Path | None = None) -> dict:
    cfg = cfg or load_config()
    questions = config.load_week7_questions()
    cohort = candidate._trace_cohort(candidate.main_ids())
    protocol = _protocol(spec, cfg)
    rows = workload.build_trace(
        "burst", cohort, questions, protocol,
        seeds=int(cfg["design"]["seeds_per_question_per_trace"]),
        seed=int(spec["rng_seed"]))
    path = Path(trace_dir or TRACE_DIR) / f"{spec['name']}.jsonl"
    sha = workload.write_trace(path, rows)
    summary = workload.trace_summary(rows)
    burst_start = float(spec["burst_start_s"])
    burst_end = burst_start + int(spec["burst_count"]) * float(spec["burst_spacing_s"])
    burst_rows = [row for row in rows if burst_start <= row["arrival_s"] < burst_end]
    return {
        "file": str(path), "sha256": sha, "summary": summary,
        "signal": summary["signal"], "filler": summary["filler"],
        "questions": summary["signal_questions"],
        "seeds_per_question": summary["seeds_per_question"],
        "burst_start_s": burst_start, "burst_end_s": burst_end,
        "burst_rows": len(burst_rows),
        "burst_signal": sum(1 for row in burst_rows if row["class"] == "signal"),
        "spec": spec,
    }


def build_all(which: str = "both", trace_dir: Path | None = None) -> dict:
    cfg = load_config()
    entries = {}
    for spec in trace_specs(which, cfg):
        entries[spec["name"]] = build_trace(spec, cfg, trace_dir)
    manifest_path = Path(trace_dir or TRACE_DIR) / "manifest-p2c.json"
    manifest = config.read_json(manifest_path) if manifest_path.exists() else {"traces": {}}
    manifest.update({"config": str(CONFIG_PATH.relative_to(config.WEEK8_ROOT)),
                     "generated_at": config.utc_now(),
                     "traces": {**manifest.get("traces", {}), **entries}})
    config.write_json(manifest_path, manifest)
    return entries


def load_prefill_config() -> dict:
    return config.read_json(PREFILL_CONFIG_PATH)


def build_prefill_trace(cfg: dict | None = None,
                        trace_dir: Path | None = None) -> dict:
    """Build the P3C prefilled-cohort trace.

    32 signal requests fill all 32 slots at t=0, a 64-request burst starts at
    10 s, and the remaining requests arrive deterministically every 6 s from
    120 s.  All requests share the same 240 s deadline.
    """
    cfg = cfg or load_prefill_config()
    design = cfg["design"]
    questions = config.load_week7_questions()
    cohort = candidate._trace_cohort(candidate.main_ids())
    protocol = candidate.protocol(seeds=int(cfg["pool"]["seeds_per_question"]))
    protocol["name"] = design["trace_name"]
    protocol["seeding"] = {"seed_base": int(design["seed_base"]),
                           "question_stride": 17, "seed_stride": 1}
    protocol["workload"]["filler_share"] = float(cfg["pool"]["filler_share"])
    signal = workload._signal_rows("burst", cohort, questions, protocol,
                                   signal_limit=int(cfg["pool"]["questions"]),
                                   seeds=int(cfg["pool"]["seeds_per_question"]))
    filler = workload._filler_rows("burst", cohort, questions, protocol, len(signal))
    rows = signal + filler
    rng = random.Random(int(design["rng_seed"]))
    rng.shuffle(rows)
    cohort_rows = [row for row in rows if row["class"] == "signal"][:int(design["cohort_size"])]
    cohort_ids = {id(row) for row in cohort_rows}
    rest = [row for row in rows if id(row) not in cohort_ids]
    burst_rows = rest[:int(design["burst_count"])]
    tail_rows = rest[int(design["burst_count"]):]
    for index, row in enumerate(cohort_rows):
        row["arrival_s"] = round(index * float(design["cohort_spacing_s"]), 6)
    for index, row in enumerate(burst_rows):
        row["arrival_s"] = round(float(design["burst_start_s"]) +
                                 index * float(design["burst_spacing_s"]), 6)
    for index, row in enumerate(tail_rows):
        row["arrival_s"] = round(float(design["tail_start_s"]) +
                                 index * float(design["tail_spacing_s"]), 6)
    condition = design["condition"]
    for row in rows:
        row["condition"] = condition
        row["deadline_s"] = float(design["deadline_seconds"])
        row["trace_id"] = f"{condition}--{row['class']}--{row['question_id']}--{row['seed']}"
    rows.sort(key=lambda row: (row["arrival_s"], row["trace_id"]))
    workload.validate_trace(rows, condition, protocol, cohort, questions,
                            allowed_signal_ids=cohort["main_ids"])
    path = Path(trace_dir or TRACE_DIR) / f"{design['trace_name']}.jsonl"
    sha = workload.write_trace(path, rows)
    burst_end = float(design["burst_start_s"]) + int(design["burst_count"]) * float(design["burst_spacing_s"])
    return {
        "file": str(path), "sha256": sha, "summary": workload.trace_summary(rows),
        "cohort": len(cohort_rows), "burst": len(burst_rows), "tail": len(tail_rows),
        "burst_start_s": float(design["burst_start_s"]), "burst_end_s": burst_end,
        "cohort_end_s": float(design["cohort_size"]) * float(design["cohort_spacing_s"]),
        "tail_start_s": float(design["tail_start_s"]),
    }


def build_prefill_all(trace_dir: Path | None = None) -> dict:
    cfg = load_prefill_config()
    entry = build_prefill_trace(cfg, trace_dir)
    manifest_path = Path(trace_dir or TRACE_DIR) / "manifest-p3c.json"
    manifest = config.read_json(manifest_path) if manifest_path.exists() else {"traces": {}}
    manifest.update({"config": str(PREFILL_CONFIG_PATH.relative_to(config.WEEK8_ROOT)),
                     "generated_at": config.utc_now(),
                     "traces": {**manifest.get("traces", {}),
                                cfg["design"]["trace_name"]: entry}})
    config.write_json(manifest_path, manifest)
    return entry


def plan_prefill(cfg: dict | None = None, trace_dir: Path | None = None) -> list[dict]:
    cfg = cfg or load_prefill_config()
    design = cfg["design"]
    path = Path(trace_dir or TRACE_DIR) / f"{design['trace_name']}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"missing prefilled trace {path}")
    phases = []
    for item in design["arms"]:
        condition = f"{design['condition']}-{item['label']}"
        phase = runner._phase(
            f"{design['trace_name']}-{item['label']}", condition, item["arm"], path,
            float(design["deadline_seconds"]),
            float(design["drain_allowance_seconds"]),
            env={"LARB_THRESHOLD": cfg["rig"]["pressure_threshold"],
                 "LARB_MAX_NUM_SEQS": cfg["rig"]["max_num_seqs"],
                 "LARB_CUT_TARGET": item["cut_target"]})
        phase["policy_label"] = item["label"]
        phase["prefill_trace"] = design["trace_name"]
        phase["burst_start_s"] = float(design["burst_start_s"])
        phase["burst_end_s"] = (float(design["burst_start_s"]) +
                                int(design["burst_count"]) * float(design["burst_spacing_s"]))
        phase["cohort_end_s"] = (int(design["cohort_size"]) *
                                 float(design["cohort_spacing_s"]))
        phase["tail_start_s"] = float(design["tail_start_s"])
        phases.append(phase)
    return phases


def plan(which: str = "both", cfg: dict | None = None,
         trace_dir: Path | None = None) -> list[dict]:
    cfg = cfg or load_config()
    phases = []
    for spec in trace_specs(which, cfg):
        path = Path(trace_dir or TRACE_DIR) / f"{spec['name']}.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"missing pilot trace {path}")
        for arm in spec["arm_order"]:
            phase = runner._phase(
                f"{spec['name']}-{arm}", spec["name"], arm, path,
                float(cfg["design"]["deadline_seconds"]),
                float(cfg["design"]["drain_allowance_seconds"]),
                env={"LARB_THRESHOLD": cfg["rig"]["pressure_threshold"],
                     "LARB_MAX_NUM_SEQS": cfg["rig"]["max_num_seqs"]})
            phase["pilot_trace"] = spec["name"]
            phase["burst_start_s"] = float(spec["burst_start_s"])
            phase["burst_end_s"] = (float(spec["burst_start_s"]) +
                                    int(spec["burst_count"]) * float(spec["burst_spacing_s"]))
            phases.append(phase)
    return phases


def run(which: str, out: Path) -> None:
    if not os.environ.get("SLURM_JOB_ID") and os.environ.get("LARB_ALLOW_NO_SLURM") != "1":
        raise RuntimeError("GPU execution requires a Slurm allocation (or LARB_ALLOW_NO_SLURM=1)")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    phases = plan(which, cfg)
    phase_file = out / "phases.json"
    if phase_file.exists():
        existing = {phase["name"] for phase in json.loads(phase_file.read_text())}
        duplicates = sorted(existing & {phase["name"] for phase in phases})
        if duplicates:
            raise SystemExit(f"{out} already has these phases: {duplicates}; use a fresh directory")
    manifest_path = out / "pilot-manifest.json"
    manifest = config.read_json(manifest_path) if manifest_path.exists() else {}
    manifest.update({
        "config": str(CONFIG_PATH.relative_to(config.WEEK8_ROOT)),
        "config_sha256": config.digest(CONFIG_PATH),
        "job": os.environ.get("SLURM_JOB_ID"),
        "started": manifest.get("started", config.utc_now()),
        "config_hashes": config.config_hashes(),
        "code_hashes": config.code_hashes(),
        "week7_source_lock": config.verify_week7_source_lock(),
    })
    manifest.setdefault("stages", {})[which] = config.utc_now()
    manifest.setdefault("traces", {}).update({
        spec["name"]: config.digest(Path(TRACE_DIR) / f"{spec['name']}.jsonl")
        for spec in trace_specs(which, cfg)})
    manifest["phases"] = sorted(set(manifest.get("phases", [])) |
                                {phase["name"] for phase in phases})
    config.write_json(manifest_path, manifest)
    runner.run_sequence(phases, out)


def load_phases(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / "phases.json"
    if path.exists():
        phases = json.loads(path.read_text())
        if phases:
            return phases
    return [json.loads(item.read_text())
            for item in sorted((Path(run_dir) / "phases").glob("*.json"))]


def load_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def build_rows(run_dir: Path, cfg: dict | None = None) -> tuple[list[dict], list[dict]]:
    cfg = cfg or load_config()
    run_dir = Path(run_dir)
    phases = load_phases(run_dir)
    requests = analysis.load_requests(run_dir)
    clients = {}
    for phase in phases:
        for client in phase.get("client_records", []):
            clients[client["key"]] = client
    rows = []
    for phase in phases:
        trace_rows = load_trace(Path(phase["trace_file"]))
        burst_start = phase.get("burst_start_s")
        burst_end = phase.get("burst_end_s")
        trace_name = phase.get("pilot_trace", phase["name"])
        for trace in trace_rows:
            key = analysis.runtime_key(phase["condition"], phase["arm"], trace)
            raw = requests.get(key)
            client = clients.get(key, {})
            scheduled = client.get("client_submitted",
                                   phase["epoch"] + trace["arrival_s"])
            deadline = scheduled + trace["deadline_s"]
            if raw:
                grade = audit.grade_record(raw, "normalized_safe")
                completion = {"normal": grade["normal"], "reason": grade["reason"],
                              "thinking_tokens": grade["thinking_tokens"],
                              "answer_tokens": grade["answer_tokens"],
                              "complete": grade["complete"]}
            else:
                grade = {"correct": False, "normal": False, "reason": "missing",
                         "extracted": None, "issue": "missing", "match": "missing"}
                completion = {"normal": False, "reason": "missing",
                              "thinking_tokens": 0, "answer_tokens": 0, "complete": False}
            finish = raw.get("finished") if raw else None
            scheduler_start = raw.get("scheduler_start") if raw else None
            latency = (finish - scheduled) if finish is not None else None
            timely = bool(latency is not None and latency <= trace["deadline_s"])
            correct = bool(raw and completion["normal"] and grade["correct"])
            in_burst = (burst_start is not None and burst_end is not None
                        and burst_start <= trace["arrival_s"] < burst_end)
            cohort_end = phase.get("cohort_end_s")
            tail_start = phase.get("tail_start_s")
            rows.append({
                "phase": phase["name"], "trace": trace_name,
                "condition": phase["condition"],
                "arm": phase.get("policy_label", phase["arm"]),
                "server_arm": phase["arm"],
                "key": key, "class": trace["class"],
                "question_id": trace["question_id"], "seed": trace["seed"],
                "scored": trace["scored"], "arrival_s": trace["arrival_s"],
                "burst": in_burst,
                "cohort": bool(cohort_end is not None and trace["arrival_s"] < cohort_end),
                "tail": bool(tail_start is not None and trace["arrival_s"] >= tail_start),
                "present": raw is not None,
                "complete": completion["complete"], "normal": completion["normal"],
                "reason": completion["reason"], "correct": correct,
                "timely": timely,
                "good": bool(trace["scored"] and correct and completion["normal"] and timely),
                "deadline": deadline, "finish": finish,
                "latency_seconds": latency,
                "queue_seconds": (max(0.0, scheduler_start - scheduled)
                                  if scheduler_start is not None else None),
                "service_seconds": (max(0.0, finish - scheduler_start)
                                    if finish is not None and scheduler_start is not None else None),
                "thinking_tokens": completion["thinking_tokens"],
                "answer_tokens": completion["answer_tokens"],
                "output_tokens": len(raw.get("token_ids", [])) if raw else 0,
                "initial_budget": raw.get("initial_budget") if raw else None,
                "final_budget": raw.get("final_budget") if raw else None,
                "cuts": len(raw.get("cut_events", [])) if raw else 0,
                "preemptions": raw.get("preemptions", 0) if raw else 0,
                "waiting_at_arrival": raw.get("waiting_at_arrival") if raw else None,
                "issue": grade["issue"] if raw else "missing",
                "extracted": grade["extracted"] if raw else None,
                "match": grade["match"] if raw else "missing",
                "exposure": trace.get("exposure"),
                "source": trace.get("source"),
            })
    return rows, phases


def _q(values, fraction):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[min(len(values) - 1, int(fraction * (len(values) - 1)))]


def summarize(rows: list[dict]) -> dict:
    scored = [row for row in rows if row["scored"]]
    n = len(scored)
    present = sum(row["present"] for row in scored)
    correct = sum(row["correct"] for row in scored)
    timely = sum(row["timely"] for row in scored)
    good = sum(row["good"] for row in scored)
    caps = sum(row["reason"] == "answer_cap" for row in scored)
    missing_box = sum(row["issue"] == "missing_complete_box" for row in scored)
    thinking = [row["thinking_tokens"] for row in scored if row["thinking_tokens"]]
    latencies = [row["latency_seconds"] for row in scored]
    queues = [row["queue_seconds"] for row in scored]
    services = [row["service_seconds"] for row in scored]
    return {
        "planned": n, "present": present, "missing": n - present,
        "errors": sum(row["present"] and not row["complete"] for row in scored),
        "correct": correct, "accuracy": correct / n if n else None,
        "correct_on_time": good, "good_rate": good / n if n else None,
        "timely": timely, "on_time_rate": timely / n if n else None,
        "deadline_misses": n - timely,
        "caps": caps, "cap_rate": caps / n if n else None,
        "missing_box_rate": missing_box / n if n else None,
        "thinking_tokens_median": statistics.median(thinking) if thinking else None,
        "latency_p50": _q(latencies, 0.50), "latency_p90": _q(latencies, 0.90),
        "latency_max": max((v for v in latencies if v is not None), default=None),
        "queue_p50": _q(queues, 0.50), "queue_p90": _q(queues, 0.90),
        "service_p50": _q(services, 0.50), "service_p90": _q(services, 0.90),
        "cuts": sum(row["cuts"] for row in scored),
        "cut_requests": len({row["key"] for row in scored if row["cuts"]}),
    }


def question_means(rows: list[dict], field: str) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        if row["scored"]:
            grouped[(row["arm"], row["question_id"])].append(
                1.0 if row[field] else 0.0)
    return {key: sum(values) / len(values) for key, values in grouped.items()}


def paired_question(rows: list[dict], arm_a: str, arm_b: str,
                    field: str = "good") -> dict:
    means = question_means(rows, field)
    questions = sorted({row["question_id"] for row in rows if row["scored"]})
    pairs = []
    for qid in questions:
        a = means.get((arm_a, qid))
        b = means.get((arm_b, qid))
        if a is None or b is None:
            continue
        pairs.append((a, b))
    if not pairs:
        return {"n": 0}
    diffs = [a - b for a, b in pairs]
    boot = stats.cluster_bootstrap(pairs, resamples=10000, seed=20261124)
    return {
        "n": len(pairs), "mean_diff": sum(diffs) / len(diffs),
        "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
        "wins": sum(1 for d in diffs if d > 0),
        "losses": sum(1 for d in diffs if d < 0),
        "ties": sum(1 for d in diffs if d == 0),
        "sign_test": stats.sign_test(diffs),
    }


def paired_response(rows: list[dict], arm_a: str, arm_b: str,
                    field: str = "correct") -> dict:
    by_key = defaultdict(dict)
    for row in rows:
        if row["scored"]:
            by_key[(row["trace"], row["question_id"], row["seed"])][row["arm"]] = row
    pairs = []
    for key, arms in sorted(by_key.items()):
        if arm_a not in arms or arm_b not in arms:
            continue
        a, b = arms[arm_a], arms[arm_b]
        pairs.append((int(a[field]), int(b[field]),
                      a["extracted"], b["extracted"]))
    if not pairs:
        return {"n": 0}
    both = sum(1 for a, b, _, _ in pairs if a and b)
    neither = sum(1 for a, b, _, _ in pairs if not a and not b)
    a_only = sum(1 for a, b, _, _ in pairs if a and not b)
    b_only = sum(1 for a, b, _, _ in pairs if not a and b)
    changes = sum(1 for _, _, x, y in pairs if x != y)
    comparable = sum(1 for _, _, x, y in pairs if x is not None and y is not None)
    return {
        "n": len(pairs), "both": both, "neither": neither,
        "a_only": a_only, "b_only": b_only,
        # Keep the same A - B orientation as paired_question.mean_diff.
        "gain": (a_only - b_only) / len(pairs),
        "discordance": (a_only + b_only) / len(pairs),
        "answer_change_fraction": changes / len(pairs),
        "answer_change_fraction_nonmissing": (changes / comparable if comparable else None),
        "sign_test": stats.sign_test([a - b for a, b, _, _ in pairs]),
    }


def _phase_metrics(run_dir: Path, phases: list[dict], cfg: dict) -> list[dict]:
    """Per-phase metrics with a worker-stream cut audit.

    The controller writes request-state before it appends the cut to the bus
    (frozen week 7 code).  A fast request can therefore finish with a correct
    final budget but an empty request-record cut list.  ``worker.jsonl`` is the
    authoritative cut stream; use it for the count and compare each cut's token
    position with the request's final cue position.
    """
    run_dir = Path(run_dir)
    requests = analysis.load_requests(run_dir)
    worker = calibrate.load_jsonl(run_dir / "worker.jsonl")
    cuts = [row for row in worker if row.get("event") == "live_reduction"]
    out = []
    for phase in phases:
        item = calibrate.phase_metrics(
            run_dir, phase, float(cfg["design"]["deadline_seconds"]),
            0.0, int(cfg["rig"]["pressure_threshold"]))
        prefix = f"{phase['condition']}--{phase['arm']}--"
        phase_cuts = [row for row in cuts if str(row.get("key", "")).startswith(prefix)]
        after_close = 0
        for cut in phase_cuts:
            raw = requests.get(cut.get("key")) or {}
            cue = raw.get("cue_start")
            if cue is not None and cut.get("tokens", 0) > cue:
                after_close += 1
        item["cut_after_close"] = after_close
        item["worker_cut_events"] = len(phase_cuts)
        item["request_cut_events"] = sum(
            len(raw.get("cut_events") or [])
            for key, raw in requests.items()
            if str(key).startswith(prefix))
        out.append(item)
    return out


def decide(result: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    rules = cfg["decision"]
    by_arm = result["by_arm"]
    paired = result["paired"]
    phases = result["phases"]
    trace_names = sorted({phase.get("pilot_trace", phase["name"]) for phase in phases})
    stage = "both" if len(trace_names) > 1 else "a"
    seen = {(phase.get("pilot_trace", phase["name"]), phase["arm"]) for phase in phases}
    expected = {(name, arm) for name in trace_names for arm in ARMS}
    phase_keys = [phase["name"] for phase in phases]
    live_metrics = [item for item in result["phase_metrics"] if item["arm"] == "live"]
    fixed_metrics = [item for item in result["phase_metrics"]
                     if item["arm"] in ("fixed4k", "fixed8k")]
    # Phase/arm coverage, not request completeness: a request-level error is a
    # failure in the planned denominator (P2C plan section 3), not a phase
    # invalidation. It is reported separately below.
    coverage_ok = seen == expected
    injection_ok = all(phase.get("injection_valid", True) for phase in phases)
    request_errors = sum(phase.get("errors", 0) for phase in phases)
    request_missing = sum(item.get("missing", 0) for item in by_arm.values())
    request_planned = sum(item.get("planned", 0) for item in by_arm.values())
    live_cuts = sum(item["cuts"] for item in live_metrics)
    live_pressure = max([(item["pressure_fraction"] or 0.0)
                         for item in live_metrics], default=0.0)
    cut_after_close = sum(item["cut_after_close"] for item in live_metrics)
    live_short = sum(item["admission_budget_short"] for item in live_metrics)
    live_long = sum(item["admission_budget_long"] for item in live_metrics)
    fixed_cuts = sum(item["cuts"] for item in fixed_metrics)
    live_each_cut = bool(live_metrics) and all(item["cuts"] > 0 for item in live_metrics)
    validity = {
        "coverage_ok": bool(coverage_ok),
        "injection_ok": bool(injection_ok),
        "request_errors": request_errors,
        "request_missing": request_missing,
        "request_planned": request_planned,
        "live_cuts": live_cuts,
        "live_each_phase_has_cut": bool(live_each_cut),
        "live_pressure_fraction_max": live_pressure,
        "cut_after_close": cut_after_close,
        "live_admission_short": live_short,
        "live_admission_long": live_long,
        "fixed_arm_cuts": fixed_cuts,
        "pass": bool(coverage_ok and injection_ok and live_each_cut
                     and live_cuts > 0 and live_pressure > 0 and cut_after_close == 0
                     and live_short > 0 and live_long > 0 and fixed_cuts == 0),
    }
    def diff(name, field):
        return (paired.get(name, {}).get(field, {}) or {}).get("mean_diff")

    slope = diff("fixed4k_vs_fixed8k", "correct")
    slope = -slope if slope is not None else None
    live_4k_good = diff("live_vs_fixed4k", "correct_on_time")
    live_4k_correct = diff("live_vs_fixed4k", "correct")
    live_8k_correct = diff("live_vs_fixed8k", "correct")
    reasons = []
    if not validity["pass"]:
        reasons.append("manipulation/coverage validity failed; see validity block")
        decision = "invalid"
    elif slope is None or slope < rules["stage_a_continue_if"]["fixed8k_minus_fixed4k_accuracy_min"]:
        reasons.append(f"fixed8k-fixed4k accuracy slope {slope} is below the "
                       f"{rules['stage_a_continue_if']['fixed8k_minus_fixed4k_accuracy_min']:.2f} floor")
        decision = "stop_slope"
    elif stage == "a":
        lim = rules["stage_a_continue_if"]
        if (live_4k_good is not None and live_4k_good < lim["live_minus_fixed4k_correct_on_time_min"]) \
                or (live_4k_correct is not None and live_4k_correct < lim["live_minus_fixed4k_accuracy_min"]) \
                or (live_8k_correct is not None and live_8k_correct < lim["live_minus_fixed8k_accuracy_min"]):
            reasons.append("Stage A live arm is materially worse than the comparators")
            decision = "stop_stage_a"
        else:
            reasons.append("Stage A valid, slope reproduced, live arm not materially worse; run Stage B")
            decision = "stage_a_continue"
    else:
        lim = rules["final_go_if"]
        if (live_4k_good is not None and live_4k_good <= 0) \
                or (live_4k_correct is not None and live_4k_correct < 0) \
                or (live_8k_correct is not None and live_8k_correct < -0.15):
            reasons.append("final stop: live is not above fixed4k on-time or accuracy, "
                           "or loses more than 15 points of accuracy against fixed8k")
            decision = "stop_final"
        elif (live_4k_good is not None and live_4k_good >= lim["live_minus_fixed4k_correct_on_time_min"]
              and live_4k_correct is not None and live_4k_correct >= lim["live_minus_fixed4k_accuracy_min"]
              and live_8k_correct is not None and live_8k_correct >= lim["live_minus_fixed8k_accuracy_min"]):
            reasons.append("final go: live beats fixed4k on correct-on-time and accuracy, "
                           "and stays within the fixed8k quality bound")
            decision = "go"
        else:
            reasons.append("final inconclusive: effect is between the stop and go thresholds at this N")
            decision = "inconclusive"
    return {
        "decision": decision,
        "stage": stage,
        "reasons": reasons,
        "validity": validity,
        "slope_fixed8k_minus_fixed4k_accuracy": slope,
        "live_minus_fixed4k_correct_on_time": live_4k_good,
        "live_minus_fixed4k_accuracy": live_4k_correct,
        "live_minus_fixed8k_accuracy": live_8k_correct,
        "thresholds": rules,
        "phase_keys": list(phase_keys),
    }


def analyse(run_dir: Path, out_dir: Path | None = None,
            cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    run_dir = Path(run_dir)
    out_dir = Path(out_dir or run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, phases = build_rows(run_dir, cfg)
    by_arm = {arm: summarize([row for row in rows if row["arm"] == arm])
              for arm in ARMS if any(row["arm"] == arm for row in rows)}
    by_arm_burst = {arm: summarize([row for row in rows
                                    if row["arm"] == arm and row["burst"]])
                    for arm in by_arm}
    by_arm_nonburst = {arm: summarize([row for row in rows
                                       if row["arm"] == arm and not row["burst"]])
                       for arm in by_arm}
    by_exposure = {}
    for exposure in sorted({row["exposure"] for row in rows if row["exposure"]}):
        by_exposure[exposure] = {
            arm: summarize([row for row in rows
                            if row["arm"] == arm and row["exposure"] == exposure])
            for arm in by_arm}
    paired = {}
    for arm_a, arm_b in (("fixed4k", "fixed8k"), ("live", "fixed4k"),
                         ("live", "arrival"), ("live", "fixed8k"),
                         ("arrival", "fixed4k"), ("arrival", "fixed8k")):
        name = f"{arm_a}_vs_{arm_b}"
        paired[name] = {
            "correct": paired_question(rows, arm_a, arm_b, "correct"),
            "correct_on_time": paired_question(rows, arm_a, arm_b, "good"),
            "response_correct": paired_response(rows, arm_a, arm_b, "correct"),
            "response_correct_on_time": paired_response(rows, arm_a, arm_b, "good"),
        }
    burst_rows = [row for row in rows if row["burst"]]
    paired_burst = {
        f"{a}_vs_{b}": {"correct": paired_question(burst_rows, a, b, "correct"),
                        "correct_on_time": paired_question(burst_rows, a, b, "good")}
        for a, b in (("fixed4k", "fixed8k"), ("live", "fixed4k"),
                     ("live", "arrival"), ("live", "fixed8k"))}
    phase_metrics = _phase_metrics(run_dir, phases, cfg)
    for arm, item in by_arm.items():
        arm_phases = [row for row in phase_metrics if row["arm"] == arm]
        item["worker_cuts"] = sum(row["cuts"] for row in arm_phases)
        item["worker_cut_requests"] = sum(row["cut_requests"] for row in arm_phases)
    result = {
        "generated_at": config.utc_now(),
        "run_dir": str(run_dir),
        "config": str(CONFIG_PATH.relative_to(config.WEEK8_ROOT)),
        "design": cfg["design"],
        "phases": phases,
        "phase_metrics": phase_metrics,
        "by_arm": by_arm,
        "by_arm_burst": by_arm_burst,
        "by_arm_nonburst": by_arm_nonburst,
        "by_exposure": by_exposure,
        "paired": paired,
        "paired_burst": paired_burst,
        "rows": rows,
        "caveats": [
            "Screening pilot, not a powered P2; the planned MDE is about 10-14 points.",
            "Caps, missing outputs, late answers and errors remain failures in the denominator.",
            "Paired CIs resample questions, not responses.",
            "The two traces use independent seed bases; Stage A is one trace, Stage B adds the second.",
            "Cut counts use worker.jsonl. The frozen controller persists request state before recording the cut, so a fast request can have a correct final budget but an empty request-record cut list.",
            "A null or inconclusive result does not prove the mechanism has no effect.",
        ],
    }
    result["decision"] = decide(result, cfg)
    config.write_json(out_dir / "pilot.json", result)
    config.write_json(out_dir / "summary.json", {
        "by_arm": by_arm, "by_arm_burst": by_arm_burst,
        "by_arm_nonburst": by_arm_nonburst, "phase_metrics": phase_metrics,
        "decision": result["decision"],
    })
    with (out_dir / "paired.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["comparison", "field", "n", "mean_diff", "ci_low", "ci_high",
                         "wins", "losses", "ties"])
        for name, block in paired.items():
            for field, item in block.items():
                if field.startswith("response_") or not item.get("n"):
                    continue
                writer.writerow([name, field, item["n"], item["mean_diff"],
                                 item["ci_low"], item["ci_high"],
                                 item["wins"], item["losses"], item["ties"]])
    write_markdown(result, out_dir / "PILOT.md")
    return result


def _fmt(value, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def write_markdown(result: dict, path: Path) -> None:
    decision = result["decision"]
    lines = [
        "# P2C quality-first burst pilot", "",
        f"Generated: {result['generated_at']}", "",
        f"Run: `{result['run_dir']}`", "",
        "## Decision", "",
        f"**{decision['decision']}** ({decision['stage']})", "",
    ]
    lines += [f"- {reason}" for reason in decision["reasons"]]
    lines += ["", "### Validity", "",
              "| check | value |", "|---|---:|"]
    for key, value in decision["validity"].items():
        lines.append(f"| {key} | {_fmt(value)} |")
    lines += ["", "### Pre-declared thresholds", "",
              "```json", json.dumps(decision["thresholds"], indent=2), "```", ""]
    lines += ["## Per-arm outcomes (all signal)", "",
              "| arm | planned | present | correct | accuracy | correct-on-time | on-time rate | "
              "caps | thinking median | cuts (worker) | latency p50 | latency p90 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for arm, item in result["by_arm"].items():
        lines.append(
            f"| {arm} | {item['planned']} | {item['present']} | {item['correct']} | "
            f"{_fmt(item['accuracy'])} | {item['correct_on_time']} | {_fmt(item['good_rate'])} | "
            f"{item['caps']} | {_fmt(item['thinking_tokens_median'], 0)} | "
            f"{item.get('worker_cuts', item['cuts'])} | "
            f"{_fmt(item['latency_p50'], 1)} | {_fmt(item['latency_p90'], 1)} |")
    lines += ["", "## Burst-window outcomes", "",
              "| arm | planned | correct | accuracy | correct-on-time | on-time rate | "
              "queue p50 | queue p90 | latency p50 | latency p90 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for arm, item in result["by_arm_burst"].items():
        lines.append(
            f"| {arm} | {item['planned']} | {item['correct']} | {_fmt(item['accuracy'])} | "
            f"{item['correct_on_time']} | {_fmt(item['good_rate'])} | "
            f"{_fmt(item['queue_p50'], 1)} | {_fmt(item['queue_p90'], 1)} | "
            f"{_fmt(item['latency_p50'], 1)} | {_fmt(item['latency_p90'], 1)} |")
    lines += ["", "## Paired comparisons", "",
              "`mean_diff` is arm A minus arm B at the question level; the CI resamples questions.", "",
              "| comparison | field | n | mean diff | 95% CI | wins / losses / ties | response gain (A−B) | sign-test p |",
              "|---|---|---:|---:|---|---:|---:|---:|"]
    for name, block in result["paired"].items():
        for field in ("correct", "correct_on_time"):
            item = block[field]
            if not item.get("n"):
                continue
            response = block.get("response_" + field, {})
            lines.append(
                f"| {name} | {field} | {item['n']} | {item['mean_diff']:+.3f} | "
                f"[{item['ci_low']:+.3f}, {item['ci_high']:+.3f}] | "
                f"{item['wins']} / {item['losses']} / {item['ties']} | "
                f"{response.get('gain', 0):+.3f} | {response.get('sign_test', {}).get('p', 1):.4f} |")
    lines += ["", "## Burst-window paired comparisons", "",
              "| comparison | field | n | mean diff | 95% CI | wins / losses / ties |",
              "|---|---|---:|---:|---|---:|"]
    for name, block in result["paired_burst"].items():
        for field in ("correct", "correct_on_time"):
            item = block[field]
            if not item.get("n"):
                continue
            lines.append(f"| {name} | {field} | {item['n']} | {item['mean_diff']:+.3f} | "
                         f"[{item['ci_low']:+.3f}, {item['ci_high']:+.3f}] | "
                         f"{item['wins']} / {item['losses']} / {item['ties']} |")
    lines += ["", "## Phase-level queue and mechanism metrics", "",
              "| phase | arm | signal | miss rate | p50 latency | p90 latency | pressure >=8 | "
              "waiting mean | waiting p90 | waiting max | cuts | cut after close | 4096 / 8192 admissions |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for item in result["phase_metrics"]:
        lines.append(
            f"| {item['phase']} | {item['arm']} | {item['measured_signal']} | "
            f"{_fmt(item['signal_miss_rate'])} | {_fmt(item['signal_latency_p50'], 1)} | "
            f"{_fmt(item['signal_latency_p90'], 1)} | {_fmt(item['pressure_fraction'])} | "
            f"{_fmt(item['waiting_mean'], 1)} | {_fmt(item['waiting_p90'])} | "
            f"{_fmt(item['waiting_max'])} | {item['cuts']} | {item['cut_after_close']} | "
            f"{item['admission_budget_short']} / {item['admission_budget_long']} |")
    lines += ["", "## Caveats", ""]
    lines += [f"- {caveat}" for caveat in result["caveats"]]
    lines.append("")
    Path(path).write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True,
                        choices=["build", "plan", "run", "analyse", "all"])
    parser.add_argument("--which", choices=["a", "b", "both"], default="both")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--trace-dir", type=Path)
    args = parser.parse_args()
    if args.stage == "build":
        entries = build_all(args.which, args.trace_dir)
        print(json.dumps({name: {key: entry[key] for key in
                                 ("file", "sha256", "signal", "filler", "questions",
                                  "seeds_per_question", "burst_rows", "burst_signal")}
                          for name, entry in entries.items()}, indent=2))
        return
    if args.stage == "plan":
        phases = plan(args.which, trace_dir=args.trace_dir)
        print(json.dumps([{"phase": p["name"], "condition": p["condition"],
                           "arm": p["arm"], "requests": p["request_count"],
                           "horizon_s": round(p["horizon_s"], 1)} for p in phases],
                         indent=2))
        return
    if args.out is None:
        raise SystemExit("--out is required for this stage")
    if args.stage in ("run", "all"):
        if args.stage == "all":
            build_all(args.which, args.trace_dir)
        run(args.which, args.out)
    if args.stage in ("analyse", "all"):
        result = analyse(args.out, args.out)
        print(json.dumps({"decision": result["decision"]["decision"],
                          "stage": result["decision"]["stage"],
                          "reasons": result["decision"]["reasons"]}, indent=2))


if __name__ == "__main__":
    main()

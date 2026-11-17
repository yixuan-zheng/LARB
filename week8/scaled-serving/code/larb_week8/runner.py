"""Week 8 GPU runner: preview, calibration, live check and P2 freeze.

This module starts the frozen week 7 server through the thin Week 8 wrapper
(which supplies the Omni-MATH question set) and reuses the week 7 replay
client, controller and telemetry.  It never modifies the frozen week 7 code.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from larb_week8 import calibrate, config, decision, preview, traces
from larb_week8.questions import load_merged_questions
from larb_scaled import client
from larb_scaled import runner as frozen_runner
from larb_scaled import workload

REPO_ROOT = config.REPO_ROOT
SERVER_MODULE = "larb_week8.server_entry"
DEFAULT_PORT = 18861
# The forced-cue smoke must exercise the same engine and controller settings as
# a scored phase (frozen rig: legacy contract, eager, 32 slots, threshold 8).
SMOKE_ENV = {"LARB_FORCE_BUDGET": 64, "LARB_FORCE_ANSWER_CAP": 64,
             "LARB_CONTRACT": "legacy", "LARB_ENFORCE_EAGER": "1",
             "LARB_THRESHOLD": 8, "LARB_MAX_NUM_SEQS": 32}


def _phase(name: str, condition: str, arm: str, trace_file: Path,
           deadline: float, drain: float, env: dict | None = None) -> dict:
    settings = {"LARB_THRESHOLD": 8, "LARB_MAX_NUM_SEQS": 32}
    if env:
        settings.update(env)
    return frozen_runner.make_phase(
        name, condition, arm, trace_file, deadline_s=deadline,
        drain_allowance_s=drain, contract="legacy", enforce_eager=True,
        injection_lag_limit_seconds=1.0, env=settings)


def plan_preview(size: int = 24) -> list[dict]:
    name = "gate-omni-preview" if size == 24 else "gate-omni-preview48"
    path = config.TRACE_DIR / f"{name}.jsonl"
    if not path.exists():
        traces.build_preview(size)
    prefix = "preview" if size == 24 else "preview48"
    return [_phase(f"{prefix}-{arm}", name, arm, path, 1800.0, 600.0)
            for arm in ("fixed4k", "fixed6k", "fixed8k")]


def plan_calibration(rates: list[float], minutes: float = 25.0) -> list[dict]:
    deadline = float(config.load_qualify()["slo"]["deadline_seconds"])
    phases = []
    for rate in rates:
        name = f"gate-omni-cal-{int(rate)}"
        path = config.TRACE_DIR / f"{name}.jsonl"
        if not path.exists():
            traces.build_calibration(rate, minutes)
        phases.append(_phase(f"cal-rate-{int(rate)}", name, "fixed8k",
                             path, deadline, 600.0))
    return phases


def plan_live(rate: float) -> list[dict]:
    name = f"gate-omni-cal-{int(rate)}"
    path = config.TRACE_DIR / f"{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"calibration trace missing: {path}")
    deadline = float(config.load_qualify()["slo"]["deadline_seconds"])
    return [_phase(f"live-{int(rate)}", name, "live", path, deadline, 600.0)]


def plan_main() -> list[dict]:
    if not config.P2_FROZEN_CONFIG.exists():
        raise FileNotFoundError("p2_main_frozen.json is missing; qualification has not passed")
    p2 = config.read_json(config.P2_FROZEN_CONFIG)
    if not p2.get("p2_authorised"):
        raise RuntimeError("P2 is not authorised")
    phases = []
    for condition in p2["conditions"]:
        path = config.TRACE_DIR / f"{condition}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        summary = workload.trace_summary(rows)
        expected_questions = 60 if condition == "low" else p2["signal_questions"]
        expected_seeds = 2 if condition == "low" else p2["seeds"]
        if summary["signal_questions"] != expected_questions:
            raise RuntimeError(
                f"{condition} trace has {summary['signal_questions']} questions, "
                f"frozen packet says {expected_questions}")
        if summary["seeds_per_question"] != expected_seeds:
            raise RuntimeError(
                f"{condition} trace has {summary['seeds_per_question']} seeds/question, "
                f"frozen packet says {expected_seeds}")
        for arm in p2["orders"][condition]:
            phases.append(_phase(
                f"main-{condition}-{arm}", condition, arm, path,
                float(p2["deadline_seconds"]), float(p2["drain_allowance_seconds"]),
                env={"LARB_MAX_NUM_SEQS": p2["max_num_seqs"],
                     "LARB_THRESHOLD": p2["pressure_threshold"]}))
    return phases


def server_env(extra: dict, out: Path, port: int) -> dict:
    # Slurm/vLLM environment values must be strings; phase settings and the
    # smoke override carry ints, so coerce at the boundary.
    env = frozen_runner.server_env({str(key): str(value) for key, value in extra.items()},
                                   out, port)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(config.WEEK8_CODE), str(config.WEEK7_CODE), env.get("PYTHONPATH", "")])
    env["LARB_DATA_DIR"] = str(config.DATA_DIR)
    env["LARB_WEEK8_ROOT"] = str(config.WEEK8_ROOT)
    return env


def run_sequence(phases: list[dict], out: Path, base_port: int = DEFAULT_PORT,
                 server_module: str = SERVER_MODULE) -> list[dict]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "requests").mkdir(exist_ok=True)
    phase_path = out / "phases.json"
    existing_phases = json.loads(phase_path.read_text()) if phase_path.exists() else []
    existing_manifest_path = out / "manifest.json"
    existing_manifest = (json.loads(existing_manifest_path.read_text())
                         if existing_manifest_path.exists() else {})
    manifest = {
        "stage": "week8",
        "job": os.environ.get("SLURM_JOB_ID"),
        "started": existing_manifest.get("started", config.utc_now()),
        "phases": [phase["name"] for phase in existing_phases] +
                  [phase["name"] for phase in phases],
        "config_hashes": config.config_hashes(),
        "code_hashes": config.code_hashes(),
        "week7_source_lock": config.verify_week7_source_lock(),
    }
    config.write_json(out / "manifest.json", manifest)
    all_records = []
    frozen_runner.kill_orphan_engines()
    groups = frozen_runner.group_by_server(phases)
    try:
        for index, (extra, group) in enumerate(groups):
            port = base_port + index
            env = server_env(extra, out, port)
            log_path = out / f"server-group-{index}.log"
            with log_path.open("w") as log:
                server = subprocess.Popen(
                    [sys.executable, "-m", server_module], cwd=str(REPO_ROOT),
                    env=env, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True)
            try:
                records = asyncio.run(client.run_phases(f"http://127.0.0.1:{port}",
                                                        group, out))
                all_records.extend(records)
                config.write_json(out / "phases.json", existing_phases + all_records)
            finally:
                try:
                    os.killpg(server.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    server.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(server.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    server.wait()
                frozen_runner.kill_orphan_engines()
    except BaseException as exc:
        manifest.update(finished=config.utc_now(), phase_records=len(all_records),
                        invalid_phases=[record["name"] for record in all_records
                                        if not record.get("injection_valid", True)],
                        error=repr(exc))
        config.write_json(out / "manifest.json", manifest)
        raise
    invalid = [record["name"] for record in all_records
               if not record.get("injection_valid", True)]
    manifest.update(finished=config.utc_now(), phase_records=len(all_records),
                    invalid_phases=invalid)
    config.write_json(out / "manifest.json", manifest)
    if invalid:
        raise RuntimeError(f"injection invalid in phases: {invalid}")


async def _smoke_async(out: Path, port: int) -> dict:
    import aiohttp
    rows = [json.loads(line) for line in (config.TRACE_DIR / "gate-omni-preview.jsonl")
            .read_text().splitlines() if line.strip()]
    questions = load_merged_questions()
    # Pick the hardest preview item; a forced cue at 64 tokens is very likely
    # to fire before a natural close, so the smoke tests the forced path.
    row = max(rows, key=lambda item: questions.get(item["question_id"], {}).get("difficulty", 0))
    key = f"{row['condition']}--fixed4k--signal--{row['question_id']}--{row['seed']}"
    base = f"http://127.0.0.1:{port}"
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        await client.wait_health(session, base, timeout=900)
        async with session.post(base + "/phase", json=dict(
                phase=row["condition"], arm="fixed4k", condition=row["condition"])) as response:
            response.raise_for_status()
        body = dict(key=key, trace_id=row["trace_id"], question_id=row["question_id"],
                    seed=row["seed"], **{"class": row["class"]}, scored=True,
                    initial_budget=None, scheduled=time.monotonic(),
                    deadline_s=row["deadline_s"])
        streamed = None
        async with session.post(base + "/generate", json=body) as response:
            response.raise_for_status()
            async for line in response.content:
                if line.strip():
                    streamed = json.loads(line)
        await asyncio.sleep(0.5)
        record = json.loads((out / "requests" / f"{key}.json").read_text())
        cue = record.get("cue_ids") or []
        tokens = record.get("token_ids") or []
        start = record.get("cue_start")
        checks = {
            "stream_finished": bool(streamed and streamed.get("finished")),
            "complete": bool(record.get("complete")),
            "error": record.get("error"),
            "cue_start": start,
            "cue_expected": 64,
            "cue_matches": bool(start is not None and cue and
                                tokens[start:start + len(cue)] == cue),
            "initial_budget": record.get("initial_budget"),
            "final_budget": record.get("final_budget"),
            "answer_cap": record.get("answer_cap"),
            "tokens": len(tokens),
        }
        checks["pass"] = bool(checks["stream_finished"] and checks["complete"]
                              and checks["error"] is None
                              and checks["cue_start"] == 64
                              and checks["cue_matches"])
        return checks


def smoke(out: Path, base_port: int = DEFAULT_PORT) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    env = server_env(SMOKE_ENV, out, base_port)
    log = (out / "server.log").open("w")
    server = subprocess.Popen([sys.executable, "-m", SERVER_MODULE], cwd=str(REPO_ROOT),
                              env=env, stdout=log, stderr=subprocess.STDOUT,
                              start_new_session=True)
    try:
        checks = asyncio.run(_smoke_async(out, base_port))
    finally:
        try:
            os.killpg(server.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(server.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            server.wait()
        log.close()
        frozen_runner.kill_orphan_engines()
    config.write_json(out / "smoke.json", checks)
    if not checks["pass"]:
        raise RuntimeError(f"GPU smoke failed: {checks}")
    return checks

    return all_records



def _analysis_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(config.WEEK8_CODE), str(config.WEEK7_CODE), env.get("PYTHONPATH", "")])
    env["LARB_DATA_DIR"] = str(config.DATA_DIR)
    return env


def _check_analysis_python(python: str) -> None:
    result = subprocess.run([python, "-c", "import math_verify"], env=_analysis_env(),
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"analysis python {python} cannot import math_verify; set LARB_ANALYSIS_PYTHON "
            "to the analysis venv")


def _run_analysis(python: str, module: str, args: list[str]) -> None:
    command = [python, "-m", module, *args]
    result = subprocess.run(command, env=_analysis_env(), cwd=str(REPO_ROOT),
                            capture_output=True, text=True)
    (config.LOGS_DIR / f"{module.replace('.', '-')}.log").write_text(
        result.stdout + result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"analysis failed: {' '.join(command)}\n{result.stdout}\n{result.stderr}")


def _read(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def _refinement_rates(bracket: dict | None, existing: list[float]) -> list[float]:
    if not bracket:
        return []
    low = calibrate._rate_of(bracket["below"])
    high = calibrate._rate_of(bracket["above"])
    if low is None or high is None or high <= low:
        return []
    midpoint = (low + high) / 2.0
    candidates = [midpoint - 25.0, midpoint, midpoint + 25.0]
    return [rate for rate in candidates if rate > 0 and rate not in existing]


def _decide_stop(out: Path, reason: str, preview_result=None,
                 calibration_result=None, live_result=None) -> dict:
    return decision.write_decision(out, False, reason, preview_result,
                                   calibration_result, live_result)


def run_all(out: Path, analysis_python: str, rates: list[float] | None = None,
            minutes: float = 25.0, skip_smoke: bool = False) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "preview" / "phases.json").exists() or (out / "calibration" / "phases.json").exists():
        raise RuntimeError(
            f"{out} already contains a qualification attempt; archive it and use a "
            "fresh LARB_OUT so coverage counts are not mixed")
    qualify = config.load_qualify()
    rates = rates or qualify["calibration"]["candidate_rates_per_hour"]
    _check_analysis_python(analysis_python)
    if not skip_smoke:
        smoke(out / "smoke")

    preview_run = out / "preview"
    run_sequence(plan_preview(24), preview_run)
    _run_analysis(analysis_python, "larb_week8.preview",
                  ["--run", str(preview_run), "--out", str(out),
                   "--preview-size", "24"])
    preview_result = _read(out / "preview-24.json")
    preview_decision = preview_result["decision"]["decision"]
    if preview_decision == "near_miss":
        preview48_run = out / "preview48"
        run_sequence(plan_preview(48), preview48_run)
        _run_analysis(analysis_python, "larb_week8.preview",
                      ["--run", str(preview48_run), "--out", str(out),
                       "--preview-size", "48"])
        preview_result = _read(out / "preview-48.json")
        preview_decision = preview_result["decision"]["decision"]
    if preview_decision != "pass":
        reason = (f"Preview ended in {preview_decision}; P2 is not authorised. "
                  "The preview record and the decision rule are preserved.")
        return _decide_stop(out, reason, preview_result=preview_result)

    calibration_run = out / "calibration"
    run_sequence(plan_calibration(rates, minutes), calibration_run)
    _run_analysis(analysis_python, "larb_week8.calibrate",
                  ["--run", str(calibration_run), "--out", str(out),
                   "--deadline", str(qualify["slo"]["deadline_seconds"]),
                   "--warmup", str(qualify["calibration"]["warmup_seconds"]),
                   "--threshold", str(qualify["frozen_rig"]["pressure_threshold"])])
    calibration_result = _read(out / "calibration.json")
    if not calibration_result.get("band_found"):
        refinement = _refinement_rates(calibration_result.get("bracket"), rates)
        if refinement:
            run_sequence(plan_calibration(refinement, minutes), calibration_run)
            _run_analysis(analysis_python, "larb_week8.calibrate",
                          ["--run", str(calibration_run), "--out", str(out),
                           "--deadline", str(qualify["slo"]["deadline_seconds"]),
                           "--warmup", str(qualify["calibration"]["warmup_seconds"]),
                           "--threshold", str(qualify["frozen_rig"]["pressure_threshold"])])
            calibration_result = _read(out / "calibration.json")
            calibration_result["refinement_rates"] = refinement
    if not calibration_result.get("band_found"):
        reason = ("Calibration found no 15-40% miss band at the pre-declared 240 s SLO "
                  "after the pre-declared refinement grid; P2 is not authorised. "
                  "The bracket and every rate are preserved for a documented stop.")
        return _decide_stop(out, reason, preview_result=preview_result,
                            calibration_result=calibration_result)

    rate = calibration_result["chosen_rate_per_hour"]
    run_sequence(plan_live(rate), calibration_run)
    _run_analysis(analysis_python, "larb_week8.calibrate",
                  ["--run", str(calibration_run), "--out", str(out),
                   "--deadline", str(qualify["slo"]["deadline_seconds"]),
                   "--warmup", str(qualify["calibration"]["warmup_seconds"]),
                   "--threshold", str(qualify["frozen_rig"]["pressure_threshold"])])
    calibration_result = _read(out / "calibration.json")
    live_result = calibration_result.get("live_check", {})
    if not live_result.get("pass"):
        reason = ("The live manipulation check failed at the calibrated rate; "
                  "P2 is not authorised.")
        return _decide_stop(out, reason, preview_result=preview_result,
                            calibration_result=calibration_result, live_result=live_result)

    cohort_variant = ("main_after_preview48"
                      if preview_result["preview_size"] == 48 else "main")
    try:
        frozen = decision.freeze_p2(rate, cohort_variant, preview_result["preview_size"],
                                    preview_result["decision"], calibration_result, live_result)
    except RuntimeError as exc:
        reason = (f"Qualification passed, but no pre-declared seed count fits the 15 h "
                  f"inner allocation: {exc}")
        return _decide_stop(out, reason, preview_result=preview_result,
                            calibration_result=calibration_result, live_result=live_result)
    reason = (f"Preview passed ({preview_result['preview_size']} items), calibration chose "
              f"{rate}/h with miss rate {calibration_result['chosen_miss_rate']:.3f}, "
              f"and the live manipulation check passed. P2 is frozen with {frozen['seeds']} seeds.")
    return decision.write_decision(out, True, reason, preview_result,
                                   calibration_result, live_result, frozen)



def dry_run(stage: str, out: Path, rates: list[float] | None = None,
            minutes: float = 25.0, rate: float | None = None) -> list[dict]:
    qualify = config.load_qualify()
    rates = rates or qualify["calibration"]["candidate_rates_per_hour"]
    if stage == "preview":
        phases = plan_preview(24)
    elif stage == "preview48":
        phases = plan_preview(48)
    elif stage == "calibration":
        phases = plan_calibration(rates, minutes)
    elif stage == "live":
        if rate is None:
            raise SystemExit("--rate is required for the live dry-run")
        phases = plan_live(rate)
    elif stage == "main":
        phases = plan_main()
    elif stage == "all":
        phases = plan_preview(24) + plan_preview(48) + plan_calibration(rates, minutes)
    elif stage == "smoke":
        phases = []
    else:
        raise ValueError(stage)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    config.write_json(out / "plan.json", phases)
    print(json.dumps([{"phase": phase["name"], "condition": phase["condition"],
                       "arm": phase["arm"], "requests": phase["request_count"],
                       "deadline_s": phase["deadline_s"],
                       "horizon_s": round(phase["horizon_s"], 1)} for phase in phases],
                     indent=2))
    return phases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True,
                        choices=["smoke", "preview", "preview48", "calibration",
                                 "live", "main", "all"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trace-dir", type=Path)
    parser.add_argument("--rates", type=float, nargs="+")
    parser.add_argument("--minutes", type=float, default=25.0)
    parser.add_argument("--rate", type=float)
    parser.add_argument("--analysis-python",
                        default=os.environ.get("LARB_ANALYSIS_PYTHON", sys.executable))
    parser.add_argument("--base-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.trace_dir:
        config.TRACE_DIR = Path(args.trace_dir)
    if args.dry_run:
        dry_run(args.stage, args.out, args.rates, args.minutes, args.rate)
        return
    if not os.environ.get("SLURM_JOB_ID") and os.environ.get("LARB_ALLOW_NO_SLURM") != "1":
        raise RuntimeError("GPU execution requires a Slurm allocation (or LARB_ALLOW_NO_SLURM=1)")
    if args.stage == "smoke":
        print(json.dumps(smoke(args.out, args.base_port), indent=2))
    elif args.stage == "preview":
        run_sequence(plan_preview(24), args.out, args.base_port)
        _run_analysis(args.analysis_python, "larb_week8.preview",
                      ["--run", str(args.out), "--out", str(args.out),
                       "--preview-size", "24"])
    elif args.stage == "preview48":
        run_sequence(plan_preview(48), args.out, args.base_port)
        _run_analysis(args.analysis_python, "larb_week8.preview",
                      ["--run", str(args.out), "--out", str(args.out),
                       "--preview-size", "48"])
    elif args.stage == "calibration":
        qualify = config.load_qualify()
        rates = args.rates or qualify["calibration"]["candidate_rates_per_hour"]
        run_sequence(plan_calibration(rates, args.minutes), args.out, args.base_port)
        _run_analysis(args.analysis_python, "larb_week8.calibrate",
                      ["--run", str(args.out), "--out", str(args.out),
                       "--deadline", str(qualify["slo"]["deadline_seconds"]),
                       "--warmup", str(qualify["calibration"]["warmup_seconds"]),
                       "--threshold", str(qualify["frozen_rig"]["pressure_threshold"])])
    elif args.stage == "live":
        if args.rate is None:
            raise SystemExit("--rate is required for the live stage")
        run_sequence(plan_live(args.rate), args.out, args.base_port)
        qualify = config.load_qualify()
        _run_analysis(args.analysis_python, "larb_week8.calibrate",
                      ["--run", str(args.out), "--out", str(args.out),
                       "--deadline", str(qualify["slo"]["deadline_seconds"]),
                       "--warmup", str(qualify["calibration"]["warmup_seconds"]),
                       "--threshold", str(qualify["frozen_rig"]["pressure_threshold"])])
    elif args.stage == "main":
        run_sequence(plan_main(), args.out, args.base_port)
        _run_analysis(args.analysis_python, "larb_week8.analyze_main",
                      ["--run", str(args.out), "--out", str(args.out / "analysis")])
        from larb_scaled import analysis
        analysis.analyze_run(args.out, args.out / "analysis-legacy")
    elif args.stage == "all":
        result = run_all(args.out, args.analysis_python, args.rates,
                         args.minutes, args.skip_smoke)
        print(json.dumps({"go": result["go"], "reason": result["reason"]}, indent=2))


if __name__ == "__main__":
    main()


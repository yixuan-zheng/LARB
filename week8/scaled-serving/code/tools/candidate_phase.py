"""Run the AIME 2025+2026 pre-P2 stages and, if frozen, P2 itself.

Stages (CPU-only ones are marked):

    build         build the 13 calibration traces and the seed-2 replicate trace
    plan          print the phase table for a stage without touching the GPU
    calibration   run the 240 s rate grid and analyse it             (GPU)
    live          run the live manipulation check at the chosen rate  (GPU)
    freeze        write the P2 packet and P2 traces from a passing
                  calibration + live pair                             (CPU)
    main          run P2 from the frozen packet                       (GPU)

Engine, contract, answer space (2,048 tokens) and window (12,288) are the frozen
week 7 values; the AIME-specific facts are the question set and the 240 s
deadline.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from larb_week8 import calibrate, candidate, runner


def _analyse(python: str, module: str, args: list[str]) -> None:
    runner._run_analysis(python, module, args)


def _calibration_args(out: Path) -> list[str]:
    qualify = candidate.load_qualify()
    return ["--run", str(out), "--out", str(out),
            "--deadline", str(qualify["slo"]["deadline_seconds"]),
            "--warmup", str(qualify["calibration"]["warmup_seconds"]),
            "--threshold", str(qualify["frozen_rig"]["pressure_threshold"])]


def _existing(out: Path) -> tuple[set[str], set[str]]:
    """Names and conditions of the phases already recorded in the run dir."""
    path = Path(out) / "phases.json"
    if not path.exists():
        return set(), set()
    phases = json.loads(path.read_text())
    return ({phase["name"] for phase in phases},
            {phase["condition"] for phase in phases})


def _require_gpu() -> None:
    if not os.environ.get("SLURM_JOB_ID") and os.environ.get("LARB_ALLOW_NO_SLURM") != "1":
        raise SystemExit("GPU stages require a Slurm allocation (or LARB_ALLOW_NO_SLURM=1)")


def _print_plan(phases: list[dict]) -> None:
    print(json.dumps([{"phase": phase["name"], "condition": phase["condition"],
                       "arm": phase["arm"], "requests": phase["request_count"],
                       "deadline_s": phase["deadline_s"],
                       "horizon_s": round(phase["horizon_s"], 1)}
                      for phase in phases], indent=2))


def _calibration_summary(result: dict) -> dict:
    """Console summary for a finished calibration run.

    The analysed rows carry their rate in the phase *condition*
    (``gate-aime-cal-<rate>``), not in a ``rate_per_hour`` field, so the rate is
    read back with the same helper the analysis uses to pick a rate.
    """
    return {"band_found": result["band_found"],
            "chosen_rate_per_hour": result["chosen_rate_per_hour"],
            "rates": [calibrate._rate_of(row) for row in result["rates"]]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", required=True,
                        choices=["build", "plan", "calibration", "live", "freeze", "main"])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--rates", type=float, nargs="+")
    parser.add_argument("--minutes", type=float, default=25.0)
    parser.add_argument("--rate", type=float)
    parser.add_argument("--analysis-python",
                        default=os.environ.get("LARB_ANALYSIS_PYTHON", sys.executable))
    parser.add_argument("--plan-stage", choices=["calibration", "live", "main"])
    args = parser.parse_args()
    qualify = candidate.load_qualify()
    rates = args.rates or qualify["calibration"]["candidate_rates_per_hour"]

    if args.stage == "build":
        calibration = candidate.build_calibration_traces(rates, args.minutes)
        replicate = candidate.build_seed2_trace()
        print(json.dumps({"calibration": {name: entry["summary"]["requests"]
                                          for name, entry in calibration.items()},
                          "replicate": {name: entry["summary"]["requests"]
                                        for name, entry in replicate.items()},
                          "prompt_margin": candidate.prompt_margin()}, indent=2))
        return

    if args.stage == "plan":
        stage = args.plan_stage or "calibration"
        if stage == "calibration":
            phases = candidate.calibration_plan(rates, args.minutes)
        elif stage == "live":
            if args.rate is None:
                raise SystemExit("--rate is required to plan the live stage")
            phases = candidate.live_plan(args.rate)
        else:
            phases = candidate.main_plan()
        _print_plan(phases)
        return

    out = Path(args.out) if args.out else None
    if out is None:
        raise SystemExit("--out is required for this stage")

    if args.stage == "calibration":
        _require_gpu()
        phases = candidate.calibration_plan(rates, args.minutes)
        _, done = _existing(out)
        duplicates = sorted({phase["condition"] for phase in phases} & done)
        if duplicates:
            raise SystemExit(f"{out} already has these rates: {duplicates}; "
                             "request only missing rates")
        out.mkdir(parents=True, exist_ok=True)
        runner.run_sequence(phases, out)
        _analyse(args.analysis_python, "larb_week8.calibrate", _calibration_args(out))
        result = json.loads((out / "calibration.json").read_text())
        print(json.dumps(_calibration_summary(result)))
        return

    if args.stage == "live":
        _require_gpu()
        if not (out / "calibration.json").exists():
            raise SystemExit(f"{out} has no calibration.json; run the calibration stage first")
        band = json.loads((out / "calibration.json").read_text())
        rate = args.rate or band.get("chosen_rate_per_hour")
        if rate is None:
            raise SystemExit("no rate in band; the live check is not authorised")
        names, _ = _existing(out)
        if any(str(name).startswith("live-") for name in names):
            raise SystemExit(f"{out} already has a live phase; use a fresh directory")
        # Live phases append to the same run so `calibrate.live_check` sees the
        # rate grid and the live phase together.
        runner.run_sequence(candidate.live_plan(float(rate)), out)
        _analyse(args.analysis_python, "larb_week8.calibrate", _calibration_args(out))
        live = json.loads((out / "calibration.json").read_text()).get("live_check", {})
        print(json.dumps({"rate": rate, "live_check_pass": live.get("pass")}))
        return

    if args.stage == "freeze":
        if not (out / "calibration.json").exists():
            raise SystemExit(f"{out} has no calibration.json; run the calibration stage first")
        band = json.loads((out / "calibration.json").read_text())
        live = band.get("live_check", {})
        if not band.get("band_found"):
            raise SystemExit("calibration found no band; freeze is not authorised")
        if not live.get("pass"):
            raise SystemExit("live check did not pass; freeze is not authorised")
        rate = float(band["chosen_rate_per_hour"])
        packet = candidate.freeze(rate, band, live)
        auth = qualify["preview"]["authorisation"]
        estimate = packet["seed_wall_time_estimates"][packet["seeds"]]
        lines = ["# P2 frozen: aime-2025-2026-v1", "",
                 f"Calibration rate: **{rate}/h** (reference miss "
                 f"{band['chosen_miss_rate']:.3f})",
                 f"Live check: **pass** ({live.get('cuts')} cuts, pressure "
                 f"{live.get('pressure_fraction')})",
                 f"Seeds: **{packet['seeds']}** on {packet['signal_questions']} questions",
                 f"Estimated inner hours: {estimate['estimated_inner_hours']:.2f}",
                 f"Preview authorisation: {auth['decision']} ({auth['basis']})",
                 "", "Run P2 with `--stage main` and a fresh output directory."]
        (out / "P2-FROZEN.md").write_text("\n".join(lines) + "\n")
        print(json.dumps({"rate": rate, "seeds": packet["seeds"],
                          "traces": packet["main_traces"]}, indent=2))
        return

    if args.stage == "main":
        _require_gpu()
        out.mkdir(parents=True, exist_ok=True)
        runner.run_sequence(candidate.main_plan(), out)
        _analyse(args.analysis_python, "larb_week8.analyze_main",
                 ["--run", str(out), "--out", str(out / "analysis")])
        from larb_scaled import analysis
        analysis.analyze_run(out, out / "analysis-legacy")
        print(json.dumps({"analysis": str(out / "analysis"), "ok": True}))
        return

    raise SystemExit(f"unknown stage {args.stage}")


if __name__ == "__main__":
    main()


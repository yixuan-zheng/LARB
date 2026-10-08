"""Run the mixed prefill+decode harness: measured (GPU) or replay (measured-cost CPU).

What this script is for
-----------------------
One invocation runs a list of width policies over one trace and writes one
crash-safe JSON record per run plus flat CSVs.  It is deliberately *not* an analysis
tool: it produces the raw per-request and per-iteration evidence, and evaluation and
plotting are separate later steps.

Two modes, and the label is never optional:

``--mode measured``  real forwards on one GPU through ``serving_lib``.
``--mode replay``    the same scheduler and SLO accounting replayed on CPU against a
                     measured cost table (``calibrate.py``).  Simulated.

Repetitions are *interleaved*: the policy order rotates each repetition, so slow
drift (clock, thermal) lands on every policy rather than on whichever ran last --
the same argument Week 1's ``Harness.sweep`` makes, applied to whole runs.

Gates: in ``measured`` mode ``validate_harness`` runs before any results are produced
and the results directory is not written unless the gates pass, unless ``--force`` is
given -- in which case every artifact is stamped ``gates: not_run``.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT / "code"))
WEEK1 = REPO / "week1" / "latency-baselines"
if str(WEEK1) not in sys.path:
    sys.path.insert(0, str(WEEK1))

import policies  # noqa: E402
import serving_core as core  # noqa: E402
import slo as slo_mod  # noqa: E402
import workload  # noqa: E402

CONTRACT_PATH = ROOT / "results" / "contract.json"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def git_info() -> dict:
    def run(*cmd):
        try:
            return subprocess.run(list(cmd), cwd=REPO, capture_output=True,
                                  text=True).stdout.strip()
        except Exception:  # pragma: no cover - git is optional
            return ""
    return {"commit": run("git", "rev-parse", "HEAD"),
            "dirty": bool(run("git", "status", "--porcelain", "--untracked-files=no"))}


def harness_provenance() -> dict:
    """Hashes of the frozen Week 1 files this harness imports (there is no forked copy)."""
    files = ["latency_lib.py", "latency_math.py", "dynamic_lib.py",
             "switch_schedules.py", "build_worker.py", "probe_cost.py"]
    out = {}
    for name in files:
        path = WEEK1 / name
        if path.exists():
            out[name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    presets = REPO / "preflight" / "code" / "presets.json"
    if presets.exists():
        out["presets_sha256"] = hashlib.sha256(presets.read_bytes()).hexdigest()[:16]
    return out


class RunWriter:
    """Crash-safe record for one invocation (the Week 1 ``RunRecord`` convention)."""

    def __init__(self, directory: Path, run_id: str):
        self.path = Path(directory) / f"{run_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {"run_id": run_id, "started_utc": utc_now(), "runs": [],
                     "completed": False}

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, default=str) + "\n")
        tmp.replace(self.path)

    def set(self, **values) -> None:
        self.data.update(values)
        self.save()

    def add_run(self, entry: dict) -> None:
        self.data["runs"].append(entry)
        self.save()

    def complete(self) -> None:
        self.data["completed"] = True
        self.data["finished_utc"] = utc_now()
        self.save()


def write_csv(path: Path, rows: list, columns: list | None = None) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = columns or list(rows[0])
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_contract(args) -> slo_mod.SLOContract:
    contract = slo_mod.SLOContract(ttft_s=args.slo_ttft_ms / 1000.0,
                                   itl_gate_s=args.slo_itl_ms / 1000.0,
                                   tpot_mean_gate_s=args.tpot_ms / 1000.0)
    if CONTRACT_PATH.exists():
        frozen = json.loads(CONTRACT_PATH.read_text()).get("primary", {})
        if frozen and (abs(frozen.get("ttft_s", contract.ttft_s) - contract.ttft_s) > 1e-9
                       or abs(frozen.get("itl_gate_s", contract.itl_gate_s)
                              - contract.itl_gate_s) > 1e-9):
            raise SystemExit(
                f"refusing to run: --slo-ttft-ms/--slo-itl-ms disagree with the frozen "
                f"contract in {CONTRACT_PATH}. Freeze SLOs before the comparison; do not "
                f"retune them after seeing results.")
    return contract


def build_config(args) -> core.EngineConfig:
    config = core.EngineConfig(
        token_budget=args.token_budget, prefill_token_budget=args.prefill_token_budget,
        decode_batch_cap=args.decode_batch_cap, prefill_chunk=args.prefill_chunk,
        prefill_batch_cap=args.prefill_batch_cap, pad_bucket=args.pad_bucket,
        max_running=args.max_running, max_seq_len=args.max_seq_len, seed=args.seed)
    config.validate()
    return config


def run_one(spec, trace, config, contract, *, mode, executor=None, cost_table=None,
            warmup_s=10.0, progress=None) -> dict:
    """Run one (policy, repetition) and return its record entry."""
    policy = policies.build_policy(spec["policy"])
    if mode == "measured":
        import serving_lib as serving

        state, report = serving.measured_run(trace, config, policy, contract, executor,
                                             progress=progress)
    else:
        import cost_table as ct

        state, report = ct.replay_run(trace, config, policy, contract, cost_table,
                                      warmup_s=warmup_s)
    report = dict(report)
    outcomes = [r.outcome() for r in state.completed] + [r.outcome() for r in state.rejected]
    return {
        "policy": policy.name, "policy_stub": bool(policy.stub),
        "policy_describe": policy.describe(), "rep": spec["rep"], "mode": mode,
        "config": config.to_dict(), "contract": contract.to_dict(), "report": report,
        "requests": slo_mod.request_rows(outcomes, contract),
        "iterations": state.iterations,
        "wall_s": state.wall_s,
    }


def summary_row(entry: dict) -> dict:
    """Flatten one run's report into the row that goes into ``summary.csv``."""
    rep, report = entry["report"], entry["report"]
    row = {
        "policy": entry["policy"], "policy_stub": entry["policy_stub"],
        "rep": entry["rep"], "mode": entry["mode"],
        "requests": rep["requests"], "completed": rep["completed"],
        "rejected": rep["rejected"], "iterations": rep["iterations"],
        "wall_s": rep["wall_s"], "drain_s": rep["drain_s"],
        "eval_window_s": rep["eval_window_s"],
        "attainment": rep["attainment"], "attainment_secondary": rep["attainment_secondary"],
        "attainment_ttft_only": rep["attainment_ttft_only"],
        "attainment_in_window": rep["attainment_in_window"],
        "goodput_trace_window": rep["goodput_trace_window"],
        "goodput_eval_window": rep["goodput_eval_window"],
        "throughput_rps": rep["throughput_rps_trace_window"],
        "fail_ttft": rep["breakdown"][slo_mod.FAIL_TTFT],
        "fail_itl": rep["breakdown"][slo_mod.FAIL_ITL],
        "fail_both": rep["breakdown"][slo_mod.FAIL_BOTH],
        "pass": rep["breakdown"][slo_mod.PASS],
        "incomplete": rep["breakdown"][slo_mod.INCOMPLETE],
        "switches_applied": rep["switches_applied"],
        "requests_with_switch": rep["requests_with_switch"],
        "mean_switches_per_request": rep["mean_switches_per_request"],
        "prefill_share": rep["prefill_share_of_scheduled_tokens"],
        "padding_waste": rep["padding_waste"],
        "queue_active_iteration_frac": rep["queue_active_iteration_frac"],
        "peak_running": rep["peak_running"], "vram_deferred": rep["vram_deferred_events"],
        "cache_rebuild_ms_total": rep.get("cache_rebuild_ms_total"),
    }
    for key in ("ttft_s", "max_itl_s", "mean_tpot_s", "e2e_s"):
        stats = report.get(key)
        if stats:
            for field in ("median", "p90", "p95", "p99", "mean"):
                row[f"{key}_{field}"] = stats.get(field)
    return row


def interleaved_specs(policy_names, reps: int) -> list:
    """Rotate the policy order each repetition so drift cannot favour one policy."""
    specs = []
    for rep in range(reps):
        order = policy_names[rep % len(policy_names):] + policy_names[:rep % len(policy_names)]
        for policy in order:
            specs.append({"policy": policy, "rep": rep})
    return specs


def build_parser() -> "argparse.ArgumentParser":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("measured", "replay"), default="measured")
    parser.add_argument("--trace", required=True)
    parser.add_argument("--rate-scale", type=float, default=1.0,
                        help="time compression t -> t/scale (scale > 1 = more load)")
    parser.add_argument("--limit", type=int, default=0, help="use only the first N requests")
    parser.add_argument("--policy", default="static_large,static_small,phase_hybrid",
                        help="comma-separated policy names (see policies.policy_names())")
    parser.add_argument("--reps", type=int, default=1,
                        help="repetitions per policy, interleaved in a rotating order")
    parser.add_argument("--token-budget", type=int, default=4096)
    parser.add_argument("--prefill-token-budget", type=int, default=2048)
    parser.add_argument("--decode-batch-cap", type=int, default=64)
    parser.add_argument("--prefill-chunk", type=int, default=0,
                        help="0 = whole prompt in one prefill forward (chunked lever)")
    parser.add_argument("--prefill-batch-cap", type=int, default=1,
                        help=">1 enables padded prefill batching (gated)")
    parser.add_argument("--pad-bucket", type=int, default=128)
    parser.add_argument("--max-running", type=int, default=96)
    parser.add_argument("--max-seq-len", type=int, default=16384)
    parser.add_argument("--seed", type=int, default=6222)
    parser.add_argument("--slo-ttft-ms", type=float, default=1000.0)
    parser.add_argument("--slo-itl-ms", type=float, default=200.0)
    parser.add_argument("--tpot-ms", type=float, default=100.0)
    parser.add_argument("--warmup-s", type=float, default=10.0)
    parser.add_argument("--gates", choices=("none", "cheap", "full"), default="cheap")
    parser.add_argument("--force", action="store_true",
                        help="write results even if gates did not pass (stamped)")
    parser.add_argument("--decode-mode", choices=("batched", "single_row"), default="batched")
    parser.add_argument("--slice-mode", default="materialize")
    parser.add_argument("--cost-table", default=None, help="required for --mode replay")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--min-sm-clock-mhz", type=float, default=1500.0)
    parser.add_argument("--progress", type=int, default=200, help="print every N iterations")
    parser.add_argument("--out", default=str(ROOT / "run-output"))
    parser.add_argument("--results", default=str(ROOT / "results"))
    parser.add_argument("--tag", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    trace = workload.load_trace(args.trace, rate_scale=args.rate_scale, limit=args.limit)
    contract = build_contract(args)
    config = build_config(args)
    policy_names = [p.strip() for p in args.policy.split(",") if p.strip()]
    run_id = f"{args.mode}-{args.tag or time.strftime('%Y%m%d-%H%M%S')}"
    writer = RunWriter(Path(args.out), run_id)
    results_dir = Path(args.results) / run_id

    runtime, gates_result, executor, cost_table = {}, None, None, None
    if args.mode == "measured":
        import latency_lib as lib
        import serving_lib as serving
        import validate_harness

        lib.prepare_runtime(argparse.Namespace())
        is_cuda = str(args.device).startswith("cuda")
        runtime["clock_ramp"] = (lib.clock_ramp(2.0, device=args.device) if is_cuda
                                 else {"skipped": True})
        runtime["clock_guard"] = (lib.wait_for_sm_clock(args.min_sm_clock_mhz)
                                  if is_cuda else {"skipped": True})
        executor, static_workers, _tok, infos = serving.build_executor(
            config, statics=("small",), device=args.device, slice_mode=args.slice_mode,
            decode_mode=args.decode_mode)
        runtime["worker"] = infos
        if args.gates != "none":
            gates_result = validate_harness.run_gates(
                executor, static_workers, trace=validate_harness.smoke_trace(),
                config=config, contract=contract, level=args.gates)
            if not gates_result["passed"] and not args.force:
                failed = [g["gate"] for g in gates_result["gates"] if not g["passed"]]
                raise SystemExit(f"gates failed ({failed}); re-run with --gates none or "
                                 f"--force to override")
    else:
        import cost_table as ct

        if not args.cost_table:
            raise SystemExit("--mode replay requires --cost-table")
        cost_table = ct.CostTable.load(args.cost_table)
        runtime["cost_table"] = cost_table.describe()

    capacity_path = ROOT / "results" / "costs" / "capacity.json"
    writer.set(
        mode=args.mode, trace={k: v for k, v in trace.to_dict().items() if k != "requests"},
        trace_requests=len(trace.requests), rate_scale=args.rate_scale,
        policies=policy_names, config=config.to_dict(), contract=contract.to_dict(),
        runtime=runtime, gates=gates_result,
        gates_status=("not_run" if args.gates == "none"
                      else ("passed" if gates_result and gates_result["passed"]
                            else "failed_forced")),
        git=git_info(), harness_provenance=harness_provenance(),
        slo_stats_backend=slo_mod.stats_backend(),
        capacity_reference=(json.loads(capacity_path.read_text())
                            if capacity_path.exists() else None))

    for spec in interleaved_specs(policy_names, max(1, args.reps)):
        started = time.time()
        entry = run_one(spec, trace, config, contract, mode=args.mode, executor=executor,
                        cost_table=cost_table, warmup_s=args.warmup_s,
                        progress=args.progress)
        entry["elapsed_s"] = time.time() - started
        writer.add_run(entry)
        row = summary_row(entry)
        print(f"[run] {entry['policy']:<14} rep={entry['rep']} "
              f"attainment={row['attainment']:.3f} "
              f"goodput={row['goodput_eval_window']:.3f}/s "
              f"ttft_p90={row.get('ttft_s_p90') or float('nan'):.0f}ms "
              f"({entry['elapsed_s']:.0f}s)", flush=True)

    writer.complete()
    results_dir.mkdir(parents=True, exist_ok=True)
    write_csv(results_dir / "summary.csv", [summary_row(e) for e in writer.data["runs"]])
    write_csv(results_dir / "requests.csv",
              [dict(r, policy=e["policy"], rep=e["rep"], mode=e["mode"])
               for e in writer.data["runs"] for r in e["requests"]])
    write_csv(results_dir / "iterations.csv",
              [dict(it, policy=e["policy"], rep=e["rep"], mode=e["mode"])
               for e in writer.data["runs"] for it in e["iterations"]])
    (results_dir / "manifest.json").write_text(json.dumps(
        {k: v for k, v in writer.data.items() if k != "runs"}, indent=1, default=str) + "\n")
    print(f"[run] wrote {writer.path}")
    print(f"[run] wrote {results_dir}/summary.csv, requests.csv, iterations.csv, manifest.json")
    print("PASS run_serving", flush=True)


if __name__ == "__main__":
    main()

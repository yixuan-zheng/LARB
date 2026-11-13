"""Phase planning and GPU job orchestration.

The planner is CPU-only and is used by --dry-run. The executor starts the local
vLLM server and drives the replay client; it never submits a Slurm job.
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from larb_scaled import analysis, client, config

REPO_ROOT = config.SCALED_ROOT.parent.parent


def load_trace(path):
    rows = []
    with Path(path).open() as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def make_phase(name, condition, arm, trace_file, deadline_s=180.0,
               drain_allowance_s=300.0, contract="legacy", enforce_eager=True,
               injection_lag_limit_seconds=1.0):
    rows = load_trace(trace_file)
    last = max(row["arrival_s"] for row in rows)
    return {
        "name": name, "condition": condition, "arm": arm,
        "trace_file": str(Path(trace_file).resolve()),
        "last_arrival_s": last, "deadline_s": deadline_s,
        "drain_allowance_s": drain_allowance_s,
        "horizon_s": last + deadline_s + drain_allowance_s,
        "injection_lag_limit_seconds": injection_lag_limit_seconds,
        "server_env": {"LARB_CONTRACT": contract,
                       "LARB_ENFORCE_EAGER": "1" if enforce_eager else "0"},
        "request_count": len(rows),
    }


def build_main_phases(trace_dir=None):
    trace_dir = Path(trace_dir) if trace_dir else config.ARTIFACTS_DIR / "traces"
    p2 = config.load_p2_main()
    protocol = config.load_protocol()
    phases = []
    for condition in p2["conditions"]:
        for arm in p2["orders"][condition]:
            phases.append(make_phase(
                f"{condition}-{arm}", condition, arm, trace_dir / f"{condition}.jsonl",
                deadline_s=p2["deadline_seconds"],
                drain_allowance_s=p2["drain_allowance_seconds"],
                contract="legacy", enforce_eager=True,
                injection_lag_limit_seconds=protocol["gates"]["injection_lag_limit_seconds"],
            ))
    return phases


def build_gate_phases(trace_dir=None):
    trace_dir = Path(trace_dir) if trace_dir else config.ARTIFACTS_DIR / "traces"
    phases = []
    for arm in ("fixed4k", "fixed8k"):
        phases.append(make_phase(f"bridge-{arm}", "gate-bridge", arm,
                                 trace_dir / "gate-bridge.jsonl", 1800, 600, "legacy", True))
    for arm in ("fixed4k", "fixed8k"):
        phases.append(make_phase(f"mechanics-{arm}", "gate-mechanics", arm,
                                 trace_dir / "gate-mechanics.jsonl", 1800, 600, "legacy", True))
    phases.append(make_phase("graphs-eager", "gate-mechanics", "fixed8k",
                             trace_dir / "gate-mechanics.jsonl", 1800, 600, "legacy", True))
    phases.append(make_phase("graphs-graph", "gate-mechanics", "fixed8k",
                             trace_dir / "gate-mechanics.jsonl", 1800, 600, "legacy", False))
    for contract in ("legacy", "short_boxed"):
        for arm in ("fixed4k", "fixed8k"):
            phases.append(make_phase(f"contract-{contract}-{arm}", "gate-contract", arm,
                                     trace_dir / "gate-contract.jsonl", 1800, 600,
                                     contract, True))
    for trace in ("gate-screen", "gate-preview"):
        for arm in ("fixed4k", "fixed6k", "fixed8k"):
            phases.append(make_phase(f"slope-{trace}-{arm}", trace, arm,
                                     trace_dir / f"{trace}.jsonl", 1800, 600, "legacy", True))
    return phases


def plan(stage, trace_dir=None):
    if stage == "p2-main":
        return build_main_phases(trace_dir)
    if stage == "p1-gates":
        return build_gate_phases(trace_dir)
    raise ValueError(stage)


def group_by_server(phases):
    groups = []
    for phase in phases:
        key = tuple(sorted(phase.get("server_env", {}).items()))
        if not groups or groups[-1][0] != key:
            groups.append((key, [phase]))
        else:
            groups[-1][1].append(phase)
    return [(dict(key), group) for key, group in groups]


def server_env(extra, out, port):
    env = dict(os.environ)
    protocol = config.load_protocol()
    env.update({
        "LARB_OUT": str(out),
        "LARB_PORT": str(port),
        "LARB_MODEL_PATH": os.environ.get("LARB_MODEL_PATH",
                                           protocol["model"]["local_path_default"]),
        "LARB_MAX_NUM_SEQS": os.environ.get("LARB_MAX_NUM_SEQS",
                                             str(protocol["engine"]["max_num_seqs"])),
        "PYTHONPATH": str(config.SCALED_ROOT / "code") + os.pathsep + env.get("PYTHONPATH", ""),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
        "VLLM_USE_FLASHINFER_SAMPLER": "0",
        "VLLM_ATTENTION_BACKEND": "FLASH_ATTN",
        "VLLM_USE_V1": "1",
    })
    env.update(extra)
    return env


def run_sequence(phases, out, base_port=18761):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "requests").mkdir(exist_ok=True)
    all_records = []
    groups = group_by_server(phases)
    for index, (extra, group) in enumerate(groups):
        port = base_port + index
        env = server_env(extra, out, port)
        log_path = out / f"server-group-{index}.log"
        with log_path.open("w") as log:
            server = subprocess.Popen([sys.executable, "-m", "larb_scaled.server"],
                                      cwd=str(REPO_ROOT), env=env,
                                      stdout=log, stderr=subprocess.STDOUT)
        try:
            records = asyncio.run(client.run_phases(f"http://127.0.0.1:{port}",
                                                    group, out))
            all_records.extend(records)
            config.write_json(out / "phases.json", all_records)
        finally:
            server.terminate()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
    return all_records


def dry_run(stage, out, trace_dir=None):
    phases = plan(stage, trace_dir)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    config.write_json(out / "plan.json", phases)
    rows = []
    for phase in phases:
        rows.append({"phase": phase["name"], "condition": phase["condition"],
                     "arm": phase["arm"], "requests": phase["request_count"],
                     "last_arrival_s": round(phase["last_arrival_s"], 1),
                     "horizon_s": round(phase["horizon_s"], 1),
                     "contract": phase["server_env"].get("LARB_CONTRACT"),
                     "eager": phase["server_env"].get("LARB_ENFORCE_EAGER")})
    print(json.dumps({"stage": stage, "phases": rows}, indent=2))
    return phases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["p2-main", "p1-gates"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trace-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--base-port", type=int, default=18761)
    args = parser.parse_args()
    if args.dry_run:
        dry_run(args.stage, args.out, args.trace_dir)
        return
    if not os.environ.get("SLURM_JOB_ID") and os.environ.get("LARB_ALLOW_NO_SLURM") != "1":
        raise RuntimeError("GPU execution requires a Slurm allocation (or LARB_ALLOW_NO_SLURM=1)")
    phases = plan(args.stage, args.trace_dir)
    manifest = dict(stage=args.stage, job=os.environ.get("SLURM_JOB_ID"),
                    started=config.utc_now(), phases=[p["name"] for p in phases],
                    config_hashes=config.config_hashes())
    config.write_json(args.out / "manifest.json", manifest)
    records = run_sequence(phases, args.out, args.base_port)
    if args.stage == "p2-main":
        analysis.analyze_run(args.out)
    manifest.update(finished=config.utc_now(), phase_records=len(records))
    config.write_json(args.out / "manifest.json", manifest)


if __name__ == "__main__":
    main()


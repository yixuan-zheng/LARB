"""Drive the measured run matrix: one GPU job, many cells, resumable and budgeted.

Design
------
* A **cell** is one (trace, rate-scale, repetition count, request limit) workload.  Cells
  are declared in ``results/matrix.json`` *before* the runs, together with the measured
  capacity they were derived from.
* Each cell runs ``run_serving.py`` with the three configurations in one process, so the
  model is loaded once per cell and the configurations are interleaved.
* ``results/logs/matrix.jsonl`` records one line per finished cell (start, end, wall
  seconds, per-policy attainment/goodput, accounting verdict), and a cell already in that
  file is **skipped** -- a job that dies half way can be resubmitted without redoing good
  runs.
* ``--budget-seconds`` stops the driver before it starts a cell it cannot finish, so a
  finite allocation is never spent on a run that will be killed mid-flight.

The driver decides nothing about the science: cells and SLOs come from the frozen
matrix/contract; it only schedules them.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"
LOG = ROOT / "results" / "logs" / "matrix.jsonl"
DEFAULT_MATRIX = ROOT / "results" / "matrix.json"


def read_done() -> dict:
    done = {}
    if LOG.exists():
        for line in LOG.read_text().splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            done[entry["cell"]] = entry
    return done


def append(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")


def cell_command(cell: dict, *, gates: str, results_tag: str) -> list:
    cmd = [sys.executable, "-u", str(CODE / "run_serving.py"),
           "--mode", "measured", "--trace", str(ROOT / "traces" / cell["trace"]),
           "--rate-scale", str(cell["rate_scale"]),
           "--policy", ",".join(cell.get("policies", ["static_large", "static_small",
                                                      "phase_hybrid"])),
           "--reps", str(cell.get("reps", 1)),
           "--tag", results_tag, "--gates", gates,
           "--out", str(ROOT / "run-output"), "--results", str(ROOT / "results"),
           "--progress", "500"]
    if cell.get("limit"):
        cmd += ["--limit", str(cell["limit"])]
    for flag in ("token_budget", "prefill_token_budget", "decode_batch_cap", "max_running",
                 "prefill_chunk", "pad_bucket", "warmup_s", "slo_ttft_ms", "slo_itl_ms"):
        if flag in cell:
            cmd += ["--" + flag.replace("_", "-"), str(cell[flag])]
    return cmd


def summarize_run_output(out_dir: Path, tag: str) -> dict:
    """Read back what the cell produced so the log itself carries the headline numbers."""
    path = out_dir / f"measured-{tag}.json"
    out = {"policies": {}, "accounting_passed": None, "run_id": f"measured-{tag}"}
    if not path.exists():
        return out
    doc = json.loads(path.read_text())
    all_passed = True
    for run in doc.get("runs", []):
        report = run["report"]
        out["policies"][f"{run['policy']}_r{run['rep']}"] = {
            "attainment": report["attainment"],
            "attainment_ttft_only": report["attainment_ttft_only"],
            "goodput_eval": report["goodput_eval_window"],
            "ttft_p50_ms": report["ttft_s"]["median"],
            "ttft_p99_ms": report["ttft_s"]["p99"],
            "itl_p95_ms": report["max_itl_s"]["p95"],
            "prefill_share": report["prefill_share_of_scheduled_tokens"],
            "queue_active_frac": report["queue_active_iteration_frac"],
            "switches": report["switches_applied"],
            "mode": report["mode"],
        }
        all_passed = all_passed and bool(run.get("accounting", {}).get("passed"))
    out["accounting_passed"] = all_passed
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    parser.add_argument("--budget-seconds", type=float, default=9000.0)
    parser.add_argument("--gates", default="cheap")
    parser.add_argument("--only", default=None, help="comma-separated cell ids to run")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    matrix = json.loads(Path(args.matrix).read_text())
    cells = matrix["cells"]
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        cells = [c for c in cells if c["id"] in wanted]
    done = read_done()
    started = time.time()
    print(f"[matrix] {len(cells)} cells declared; {len(done)} already finished", flush=True)

    for cell in cells:
        if cell["id"] in done:
            print(f"[matrix] skip {cell['id']} (already done)", flush=True)
            continue
        elapsed = time.time() - started
        remaining = args.budget_seconds - elapsed
        estimate = float(cell.get("estimate_s", 400.0))
        if estimate > remaining:
            print(f"[matrix] stop before {cell['id']}: estimate {estimate:.0f}s with "
                  f"{remaining:.0f}s of budget left", flush=True)
            break
        tag = f"cell-{cell['id']}"
        cmd = cell_command(cell, gates=args.gates, results_tag=tag)
        print(f"[matrix] cell {cell['id']}: trace={cell['trace']} "
              f"rate_scale={cell['rate_scale']} reps={cell.get('reps', 1)} "
              f"limit={cell.get('limit')} estimate={estimate:.0f}s", flush=True)
        if args.dry_run:
            print("[matrix]   " + " ".join(cmd), flush=True)
            continue
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=str(ROOT))
        wall = time.time() - t0
        entry = {"cell": cell["id"], "trace": cell["trace"],
                 "rate_scale": cell["rate_scale"], "reps": cell.get("reps", 1),
                 "limit": cell.get("limit"), "returncode": proc.returncode, "wall_s": wall,
                 "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
                 "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        entry.update(summarize_run_output(ROOT / "run-output", tag))
        append(entry)
        print(f"[matrix] cell {cell['id']} rc={proc.returncode} in {wall:.0f}s", flush=True)
        for key, value in sorted(entry.get("policies", {}).items()):
            print(f"[matrix]   {key:<24} attain={value['attainment']:.3f} "
                  f"goodput={value['goodput_eval']:.3f}/s "
                  f"ttft_p50={value['ttft_p50_ms']:.0f}ms", flush=True)
    print(f"[matrix] done in {time.time() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()

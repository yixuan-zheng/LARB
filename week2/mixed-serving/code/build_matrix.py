"""Derive the run matrix from the *measured* capacity, before any policy run.

The ladder is the science, not the plumbing: which loads count as under-loaded,
saturated, overloaded and backlog-inducing has to come from measurement and be frozen
before the comparison, or the comparison can be tuned after the fact.  This script does
exactly that and nothing else:

1. read ``results/costs/capacity.json`` (measured through the loop by ``calibrate.py``);
2. for each chosen trace, read its own mean arrival rate;
3. convert the capacity targets (0.5x, 0.9x, 1.3x, 2.0x of measured capacity) into
   ``--rate-scale`` values for that trace;
4. write ``results/matrix.json`` with the cells, the derivations and a wall-time estimate
   used only for budgeting the allocation.

Repetitions: the primary cells (the steady window, where the lever should show) get two
repetitions so the reproducibility spread is measurable; secondary cells get one, and the
trace's steady-state control is run at a single intermediate load.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

import workload  # noqa: E402

#: Plan keys that are engine configuration rather than workload, passed straight to
#: ``run_serving.py`` (and therefore identical for every policy inside a cell).
ENGINE_OVERRIDES = ("max_running", "decode_batch_cap", "token_budget", "prefill_token_budget",
                    "pad_bucket", "prefill_chunk", "prefill_batch_cap", "warmup_s",
                    "slo_ttft_ms", "slo_itl_ms")

#: fractions of measured capacity that define the ladder (frozen here, used everywhere).
LADDER = {"underloaded": 0.5, "saturated": 0.9, "overloaded": 1.3, "backlog": 2.0}


def build(capacity_path: Path, traces_dir: Path, plan: list,
          max_run_seconds: float = 300.0) -> dict:
    """Derive cells.  ``max_run_seconds`` caps each *run* by limiting its request count.

    The cap is applied identically to every policy and is recorded per cell, so a
    shortened cell is a documented property of the workload rather than a quiet
    difference between configurations.  It exists so that one cell (three configurations
    x repetitions) fits inside a bounded slice of the allocation.
    """
    capacity = json.loads(capacity_path.read_text())
    service = capacity["service"]
    sec_per_request = service["gpu_seconds_per_request"]
    cells, derivation = [], {}
    for spec in plan:  # each spec: trace + levels (+ optional fractions/reps/limit/overrides)
        trace_path = traces_dir / spec["trace"]
        stats = workload.load_trace(trace_path).summary()
        trace_rps = stats["mean_rps"]
        derivation[spec["trace"]] = {
            "mean_rps": trace_rps, "requests": stats["requests"],
            "span_s": stats["span_s"],
            "mean_prompt_tokens": stats["prompt_tokens"]["mean"],
            "mean_output_tokens": stats["output_tokens"]["mean"],
        }
        fractions = dict(LADDER, **(spec.get("fractions") or {}))
        for level in spec["levels"]:
            target = fractions[level] * service["capacity_rps"]
            rate_scale = target / trace_rps
            arrivals_rps = trace_rps * rate_scale
            limit = int(spec.get("limit", 0)) or stats["requests"]
            # Cap the request count so the GPU time of one run stays bounded; the limit
            # only ever shortens the window (arrivals are in time order).
            if sec_per_request > 0:
                allowed = int(max_run_seconds / sec_per_request)
                limit = min(limit, max(50, allowed))
            n_requests = min(stats["requests"], limit)
            wall_trace = n_requests / arrivals_rps if arrivals_rps else 0.0
            wall_work = n_requests * sec_per_request
            run_estimate = max(wall_trace, wall_work / 0.9) + 75.0
            n_policies = 3
            cell = {
                "id": f"{spec['id']}-{level}",
                "trace": spec["trace"],
                "rate_scale": round(rate_scale, 3),
                "reps": spec.get("reps", 1),
                "limit": n_requests if n_requests < stats["requests"] else 0,
                "level": level,
                "fraction_of_capacity": fractions[level],
                "target_rps": round(target, 3),
                "arrivals_rps": round(arrivals_rps, 3),
                "x_capacity": round(arrivals_rps / service["capacity_rps"], 3),
                "requests_used": n_requests,
                # Wall-time estimates used only to budget the allocation.  ``estimate_s``
                # is the whole cell (policies x repetitions), because that is what the
                # driver has to fit before it starts the cell.
                "estimate_run_s": round(run_estimate, 0),
                "estimate_s": round(run_estimate * spec.get("reps", 1) * n_policies, 0),
                "truncated_window": n_requests < stats["requests"],
                "notes": spec.get("notes", ""),
            }
            # Engine overrides are carried through to the runner verbatim, so a cap set in
            # the plan actually reaches the engine (they are part of the cell definition).
            for key in ENGINE_OVERRIDES:
                if key in spec:
                    cell[key] = spec[key]
            cells.append(cell)
    try:
        derived_from = str(Path(capacity_path).resolve().relative_to(ROOT))
    except ValueError:
        derived_from = str(capacity_path)
    return {"derived_from": derived_from,
            "capacity": capacity, "ladder_fractions": LADDER,
            "max_run_seconds": max_run_seconds, "trace_stats": derivation,
            "policies": ["static_large", "static_small", "phase_hybrid"], "cells": cells}


DEFAULT_PLAN = [
    {"id": "steady", "trace": "azure_conv_steady.json",
     "levels": ["underloaded", "saturated", "overloaded", "backlog"], "reps": 2,
     "notes": "representative load; the primary regime ladder"},
    {"id": "burst", "trace": "azure_conv_burst.json",
     "levels": ["saturated", "backlog"], "reps": 1,
     "notes": "highest-rate real window; short prompts, so decode-heavy"},
    {"id": "mixshift", "trace": "azure_conv_mixshift.json",
     "levels": ["overloaded"], "reps": 1,
     "notes": "largest change in request-length mix between halves"},
    {"id": "code", "trace": "azure_code_steady.json",
     "levels": ["overloaded", "backlog"], "reps": 1, "limit": 300,
     "notes": "prefill-heavy control (p50 output 13 tokens); limited to 300 requests so "
              "a cell fits the budget"},
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--capacity", default=str(ROOT / "results" / "costs" / "capacity.json"))
    parser.add_argument("--traces", default=str(ROOT / "traces"))
    parser.add_argument("--out", default=str(ROOT / "results" / "matrix.json"))
    parser.add_argument("--plan", default=None, help="JSON file overriding the default plan")
    parser.add_argument("--reps", type=int, default=None, help="override reps for all cells")
    parser.add_argument("--max-run-seconds", type=float, default=300.0,
                        help="cap each run's request count so its GPU time stays bounded")
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).read_text()) if args.plan else DEFAULT_PLAN
    matrix = build(Path(args.capacity), Path(args.traces), plan, args.max_run_seconds)
    if args.reps:
        for cell in matrix["cells"]:
            cell["reps"] = args.reps
    Path(args.out).write_text(json.dumps(matrix, indent=1) + "\n")
    total = sum(c["estimate_s"] * c["reps"] for c in matrix["cells"])
    print(f"[matrix] wrote {args.out}: {len(matrix['cells'])} cells, "
          f"estimated {total / 60:.0f} min of GPU time "
          f"(capacity {matrix['capacity']['service']['capacity_rps']:.2f} req/s)")
    for cell in matrix["cells"]:
        print(f"[matrix]   {cell['id']:<22} {cell['trace']:<26} "
              f"lambda={cell['rate_scale']:<5} x_cap={cell['x_capacity']:<5} "
              f"reps={cell['reps']} reqs={cell['requests_used']:<5} "
              f"est={cell['estimate_s']:.0f}s/cell")


if __name__ == "__main__":
    main()
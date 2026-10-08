"""Build the harness's cost table: seed it from frozen Week 1 results, or measure it.

Two modes, and the difference between them is the whole point:

``--mode seed``
    Turns the *already tracked* Week 1 evidence into a cost table: prefill cells
    from ``week1/latency-baselines/results/latency_profile.csv`` (S2, per-preset
    prefill at batch 1/4), decode cells from ``week2/decode-study/results/timing/
    summary.csv`` (paired Large/Small decode steps, batch 1-64) and the switch cost
    from ``week1/latency-baselines/results/switch_summary.json`` (S8 host apply, S9
    boundary).  This lets the CPU replay and the load ladder be planned *before* any
    GPU hour is spent, and every cell carries the file it came from.  It is a
    seed, not a measurement: the table's ``source.kind`` says ``week1_tracked_seed``.

``--mode measure``
    Measures the *loop's own* forwards through the same code path the runs use
    (the executor's prefill and batched-decode forwards), so the replay cross-check
    is checking the loop's real behaviour rather than a different microbenchmark.
    Writes ``source.kind = "measured_loop"``.

Both modes also write ``capacity.json``: measured prefill/decode throughput per
preset, the implied service capacity, and a recommended arrival-rate ladder.  The
ladder is what the run manifests cite when they say which loads count as
under-loaded, saturated and overloaded, so it is computed *before* any policy
comparison and never tuned afterwards.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT / "code"))

import cost_table  # noqa: E402
import serving_core as core  # noqa: E402

WEEK1_RESULTS = REPO / "week1" / "latency-baselines" / "results"
DECODE_STUDY = REPO / "week2" / "decode-study" / "results" / "timing" / "summary.csv"
#: Grid the loop uses, and therefore the grid that must be measured.
PREFILL_CHUNKS = (128, 256, 512, 1024, 2048, 4096)
DECODE_BATCHES = (1, 2, 4, 8, 16, 24, 32, 48, 64)


def _read_csv(path):
    with Path(path).open(newline="") as fh:
        return list(csv.DictReader(fh))


def _parse_grid_key(key: str) -> tuple:
    """``large_L1024_B4`` -> (1024, 4); s2 records carry the grid in the key."""
    length = batch = None
    for part in key.split("_"):
        if part.startswith("L") and part[1:].isdigit():
            length = int(part[1:])
        if part.startswith("B") and part[1:].isdigit():
            batch = int(part[1:])
    return length, batch


def seed_from_week1(week1_results: Path = WEEK1_RESULTS,
                    decode_study_csv: Path = DECODE_STUDY) -> dict:
    """Assemble a cost table from the frozen Week 1 / decode-study artifacts."""
    prefill_cells, provenance = [], {}
    rows = _read_csv(week1_results / "latency_profile.csv")
    for row in rows:
        if row.get("scenario") != "s2_prefill" or not row.get("gpu_ms_median"):
            continue
        length, batch = _parse_grid_key(row.get("key", ""))
        if not length or not batch:
            continue
        prefill_cells.append({"preset": row["preset"], "batch": int(batch),
                              "chunk": int(length), "ctx": 0,
                              "n": int(batch), "ms": float(row["gpu_ms_median"]),
                              "source": "week1 s2_prefill gpu_ms_median"})
    provenance["prefill"] = {
        "file": "week1/latency-baselines/results/latency_profile.csv",
        "scenario": "s2_prefill", "cells": len(prefill_cells),
        "measure": "median GPU ms of a prefill of `chunk` tokens at `batch`"}

    decode_cells = []
    if Path(decode_study_csv).exists():
        for row in _read_csv(decode_study_csv):
            if row.get("status") != "complete":
                continue
            for preset, column in (("large", "large_wall_ms"),
                                   ("small", "small_wall_ms")):
                if not row.get(column):
                    continue
                decode_cells.append({"preset": preset, "batch": int(row["batch"]),
                                     "ctx": int(row["context"]), "n": 40,
                                     "ms": float(row[column]),
                                     "source": "decode-study paired median wall ms"})
    provenance["decode"] = {
        "file": "week2/decode-study/results/timing/summary.csv",
        "cells": len(decode_cells),
        "measure": "median synchronised wall ms of one decode step at `batch`/`ctx`",
        "note": "decode width is unresolvable in this runtime (decode study); the "
                "ctx-2048 rows are the conservative single cell per batch"}

    switch = {"apply_ms": 0.087, "boundary_ms": 0.60}
    summary_path = week1_results / "switch_summary.json"
    if summary_path.exists():
        doc = json.loads(summary_path.read_text())
        try:
            switch["apply_ms"] = float(
                doc["s8_switch_mechanism"][0]["switching"]["switch_op_us"]["median"]) / 1000.0
        except (KeyError, TypeError, IndexError, ValueError):
            pass
        provenance["switch"] = {
            "file": "week1/latency-baselines/results/switch_summary.json",
            "measure": "S8 host apply median; S9 boundary worst case"}
    return {"schema_version": 1,
            "source": {"kind": "week1_tracked_seed",
                       "note": "NOT a loop measurement: reuse of frozen Week 1 cells",
                       "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "provenance": provenance},
            "cells": {"prefill": prefill_cells, "decode": decode_cells, "switch": switch},
            "kv_bytes_per_token": cost_table.DEFAULT_KV_BYTES_PER_TOKEN,
            "vram_budget_bytes": cost_table.DEFAULT_VRAM_BUDGET_BYTES}


# --------------------------------------------------------------------------- #
# Capacity and the load ladder
# --------------------------------------------------------------------------- #
def capacity_report(table_doc: dict, trace_stats: dict | None = None) -> dict:
    """Measured throughput per preset, the implied service capacity, and a ladder.

    The ladder is chosen from measurement, not from a guess.  ``lambda = 1`` is the
    arrival rate at which the prefill and decode work the trace asks for equals the
    measured capacity of the static large configuration; a trace whose own mean rate
    differs is scaled with ``--rate-scale``.  Nothing here is tuned after seeing a
    policy result: the ladder is computed before the comparison runs.
    """
    cells = table_doc["cells"]
    prefill_by_preset, decode_by_preset = {}, {}
    for row in cells["prefill"]:
        if int(row["batch"]) == 1:
            prefill_by_preset.setdefault(row["preset"], []).append(row)
    for row in cells["decode"]:
        decode_by_preset.setdefault(row["preset"], []).append(row)

    out = {"reference": "batch-1 prefill (the loop's default path), largest measured "
                        "decode batch", "presets": {}}
    for preset in sorted(set(prefill_by_preset) | set(decode_by_preset)):
        prefill_rows = sorted(prefill_by_preset.get(preset, []), key=lambda r: r["chunk"])
        decode_rows = sorted(decode_by_preset.get(preset, []), key=lambda r: r["batch"])
        prefill_ms_per_token = None
        if prefill_rows:
            best = min(prefill_rows, key=lambda r: r["ms"] / max(1, r["chunk"]))
            prefill_ms_per_token = best["ms"] / max(1, best["chunk"])
        decode_tok_s = None
        if decode_rows:
            best = max(decode_rows, key=lambda r: r["batch"])
            decode_tok_s = best["batch"] * 1000.0 / best["ms"]
        out["presets"][preset] = {
            "prefill_ms_per_token": prefill_ms_per_token,
            "prefill_tokens_per_s": (1000.0 / prefill_ms_per_token
                                     if prefill_ms_per_token else None),
            "decode_tokens_per_s": decode_tok_s,
            "decode_ms_at_largest_batch": decode_rows[-1]["ms"] if decode_rows else None,
        }

    if trace_stats:
        prompt_tokens = float(trace_stats["prompt_tokens"]["mean"])
        output_tokens = float(trace_stats["output_tokens"]["mean"])
        ref = out["presets"].get("large", {})
        prefill_tps, decode_tps = ref.get("prefill_tokens_per_s"), \
            ref.get("decode_tokens_per_s")
        if prefill_tps and decode_tps:
            prefill_s = prompt_tokens / prefill_tps
            decode_s = output_tokens / decode_tps
            per_request_s = prefill_s + decode_s
            capacity_rps = 1.0 / per_request_s if per_request_s > 0 else None
            out["service"] = {
                "mean_prompt_tokens": prompt_tokens, "mean_output_tokens": output_tokens,
                "gpu_seconds_per_request": per_request_s,
                "capacity_rps": capacity_rps,
                "prefill_time_fraction": prefill_s / per_request_s if per_request_s else None,
                "decode_time_fraction": decode_s / per_request_s if per_request_s else None,
            }
            if capacity_rps:
                out["load_ladder_rps"] = {
                    "underloaded": 0.5 * capacity_rps,
                    "saturated": 0.9 * capacity_rps,
                    "overloaded": 1.3 * capacity_rps,
                    "backlog_inducing": 2.0 * capacity_rps,
                    "note": "requests/s; --rate-scale = ladder rate / the trace "
                            "window's own mean rate",
                }
                trace_rps = float(trace_stats.get("mean_rps") or 0.0)
                if trace_rps > 0:
                    out["recommended_rate_scales"] = {
                        name: value / trace_rps
                        for name, value in out["load_ladder_rps"].items()
                        if isinstance(value, float)}
                    out["recommended_rate_scales"]["trace_mean_rps"] = trace_rps
                    out["recommended_rate_scales"]["note"] = (
                        "time-compression factors for --rate-scale on THIS trace; "
                        "derive them before any policy comparison and do not retune")
    return out


# --------------------------------------------------------------------------- #
# Measuring the loop's own forwards
# --------------------------------------------------------------------------- #
def measure(*, statics=("small",), device="cuda", dtype=None, reps=5,
            prefill_chunks=PREFILL_CHUNKS, decode_batches=DECODE_BATCHES,
            min_sm_clock_mhz=1500, clock_ramp_s=2.0, verbose=True) -> dict:
    """Measure the loop's own forwards and return a cost table in the replay schema."""
    import torch

    import latency_lib as lib
    import serving_lib as serving

    dtype = dtype or torch.bfloat16
    lib.prepare_runtime(argparse.Namespace())
    is_cuda = str(device).startswith("cuda")
    clock_info = lib.clock_ramp(clock_ramp_s, device=device if is_cuda else "cpu")
    guard = lib.wait_for_sm_clock(min_sm_clock_mhz) if is_cuda else {"skipped": True}
    config = core.EngineConfig(token_budget=8, prefill_token_budget=8, decode_batch_cap=8,
                               prefill_batch_cap=1, max_running=8)
    executor, _statics, _tok, infos = serving.build_executor(
        config, statics=statics, device=device, dtype=dtype, slice_mode="materialize",
        verbose=verbose)

    def fake(prompt_tokens, output_tokens, rid):
        state = core.ReqState(rid, 0.0, int(prompt_tokens), int(output_tokens))
        executor.on_admit(state, config)
        return state

    def timed(res):
        return res["gpu_ms"] if is_cuda else res["wall_ms"]

    prefill_cells, decode_cells = [], []
    for preset in ("large", "small"):
        for chunk in prefill_chunks:
            samples = []
            for rep in range(reps):
                req = fake(chunk, 1, f"p-{preset}-{chunk}-{rep}")
                assignment = core.PrefillAssignment(req.request_id, chunk, True, chunk)
                samples.append(timed(executor._prefill_forward(assignment, preset)))  # noqa: SLF001
                executor.on_retire(req)
            prefill_cells.append({"preset": preset, "batch": 1, "chunk": int(chunk),
                                  "ctx": 0, "n": reps, "ms": statistics.median(samples),
                                  "source": "loop _prefill_forward at batch 1"})
            print(f"[calibrate] prefill {preset:<6} chunk={chunk:<5} "
                  f"{prefill_cells[-1]['ms']:8.2f} ms", flush=True)
    for preset in ("large", "small"):
        for batch in decode_batches:
            samples = []
            for rep in range(reps):
                rows = []
                for i in range(batch):
                    req = fake(64, 8, f"d-{preset}-{batch}-{rep}-{i}")
                    executor._prefill_forward(  # noqa: SLF001
                        core.PrefillAssignment(req.request_id, 64, True, 64), preset)
                    rows.append(req.request_id)
                samples.append(timed(executor._decode_batched(rows, preset)))  # noqa: SLF001
                for rid in rows:
                    executor.on_retire(executor.states[rid])
            decode_cells.append({"preset": preset, "batch": int(batch), "ctx": 64,
                                 "n": reps, "ms": statistics.median(samples),
                                 "source": "loop _decode_batched at context 64"})
            print(f"[calibrate] decode  {preset:<6} batch={batch:<3} "
                  f"{decode_cells[-1]['ms']:8.2f} ms", flush=True)
    applies = executor.controller.apply_times_ms
    return {"schema_version": 1,
            "source": {"kind": "measured_loop",
                       "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "device": device, "dtype": str(dtype), "reps": reps,
                       "clock_ramp": clock_info, "clock_guard": guard,
                       "worker": infos, "executor": executor.describe(),
                       "note": "measured through the loop's own forwards, not a "
                               "separate microbenchmark"},
            "cells": {"prefill": prefill_cells, "decode": decode_cells,
                      "switch": {"apply_ms": float(statistics.median(applies))
                                 if applies else 0.0,
                                 "boundary_ms": 0.60}},
            "kv_bytes_per_token": serving.KV_BYTES_PER_TOKEN,
            "vram_budget_bytes": serving.DEFAULT_VRAM_BUDGET_BYTES}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("seed", "measure", "capacity"), default="seed")
    parser.add_argument("--out", default=str(ROOT / "results" / "costs"))
    parser.add_argument("--table", default=None, help="table to analyse (--mode capacity)")
    parser.add_argument("--trace", default=None, help="trace whose statistics size the ladder")
    parser.add_argument("--week1-results", default=str(WEEK1_RESULTS))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--prefill-chunks", default=",".join(str(c) for c in PREFILL_CHUNKS))
    parser.add_argument("--decode-batches", default=",".join(str(b) for b in DECODE_BATCHES))
    args = parser.parse_args()

    import workload

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "seed":
        doc = seed_from_week1(Path(args.week1_results))
    elif args.mode == "measure":
        doc = measure(device=args.device, reps=args.reps,
                      prefill_chunks=[int(x) for x in args.prefill_chunks.split(",")],
                      decode_batches=[int(x) for x in args.decode_batches.split(",")])
    else:
        if not args.table:
            parser.error("--mode capacity needs --table")
        doc = json.loads(Path(args.table).read_text())

    if args.mode != "capacity":
        table_path = out_dir / f"cost_table_{args.mode}.json"
        table_path.write_text(json.dumps(doc, indent=1) + "\n")
        print(f"[calibrate] wrote {table_path}")
    stats = workload.load_trace(args.trace).summary() if args.trace else None
    report = capacity_report(doc, stats)
    report["trace"] = args.trace
    capacity_path = out_dir / "capacity.json"
    capacity_path.write_text(json.dumps(report, indent=1) + "\n")
    print(f"[calibrate] wrote {capacity_path}")
    print(json.dumps(report.get("service", {}), indent=1))
    print(json.dumps(report.get("load_ladder_rps", {}), indent=1))


if __name__ == "__main__":
    main()


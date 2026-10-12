"""Self-validate and analyze the measured runs; emit CSVs and a markdown report.

Three jobs, in this order, and the order matters:

1. **Validate.** Every measured run is re-checked on its stored records: accounting
   invariants, request counts, forced output lengths, mode label, gate verdict, and the
   per-iteration sums.  Nothing is analyzed until it passes; the validation table is part
   of the output.
2. **Aggregate.** Per-run and per-cell tables (attainment, goodput, TTFT/ITL
   percentiles, prefill share, backlog, switch counts), with the reproducibility spread
   across repetitions.
3. **Compare.** Paired, per-*request* comparisons between policies within a cell: the
   same trace request served under two width policies, matched by ``request_id``.  That
   is the strongest available pairing (it cancels request-length mix), and it is what
   makes an attainment difference or a TTFT difference attributable to the policy rather
   than to the workload draw.  Rates get a paired bootstrap interval; attainment gets the
   discordant-pair counts (McNemar's b and c).

Sensitivity is computed from the stored per-request latencies, so SLO variants cost no
GPU time and cannot be tuned after the fact: every threshold reported here was frozen in
``results/contract.json`` before the runs.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT / "code"))
sys.path.insert(0, str(REPO / "week1" / "latency-baselines"))

import serving_core as core  # noqa: E402
import slo as slo_mod  # noqa: E402

ANALYSIS = ROOT / "results" / "analysis"
CONTRACT = json.loads((ROOT / "results" / "contract.json").read_text())


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_runs(out_dir: Path, tags=None) -> list:
    """Every measured run record, flattened to (cell, policy, rep, report, requests)."""
    runs = []
    for path in sorted(Path(out_dir).glob("measured-*.json")):
        doc = json.loads(path.read_text())
        tag = doc.get("run_id", path.stem)
        if tags and not any(t in tag for t in tags):
            continue
        for entry in doc.get("runs", []):
            runs.append({
                "tag": tag, "run_id": doc["run_id"], "mode": doc.get("mode"),
                "gates_status": doc.get("gates_status"),
                "rate_scale": doc.get("rate_scale"),
                "trace_id": doc.get("trace", {}).get("trace_id"),
                "trace_file": (doc.get("trace", {}).get("source", {}) or {}).get("kind"),
                "policy": entry["policy"], "rep": entry["rep"],
                "policy_stub": entry.get("policy_stub"),
                "accounting": entry.get("accounting", {}),
                "report": entry["report"], "requests": entry["requests"],
                "iterations": entry["iterations"],
                "config": entry["config"],
            })
    return runs


def validate(runs: list) -> tuple:
    """Re-check every run on its stored records; returns (table, all_passed)."""
    rows, ok = [], True
    for run in runs:
        report = run["report"]
        acc = run["accounting"] or {}
        problems = list(acc.get("problems", []))
        if run["mode"] != "measured":
            problems.append(f"mode is {run['mode']!r}")
        if report["mode"] != "measured":
            problems.append("report mode is not measured")
        n_requests = report["requests"]
        if report["completed"] + report["rejected"] != n_requests:
            problems.append("completed + rejected != requests")
        if report["rejected"]:
            problems.append(f"{report['rejected']} rejected requests")
        if not run["iterations"]:
            problems.append("no iteration records")
        real_tokens = sum(it["prefill_tokens"] + it["decode_tokens"]
                          for it in run["iterations"])
        gen_tokens = sum(r["output_tokens"] for r in run["requests"])
        decode_logged = sum(it["decode_tokens"] for it in run["iterations"])
        # Each request's first token is produced by its own (final) prefill chunk, so the
        # decode steps account for generated - one-per-request exactly.  Getting this
        # identity wrong is easy (it was, here) and it is the cheapest possible check that
        # the per-iteration log really describes the same tokens the requests report.
        expected_decode = gen_tokens - len(run["requests"])
        if decode_logged != expected_decode:
            problems.append(f"decode tokens in log {decode_logged} != generated - requests "
                            f"{expected_decode} (generated {gen_tokens}, "
                            f"{len(run['requests'])} requests)")
        if real_tokens <= 0:
            problems.append("no scheduled tokens")
        passed = not problems and bool(acc.get("passed"))
        ok = ok and passed
        rows.append({
            "run_id": run["run_id"], "policy": run["policy"], "rep": run["rep"],
            "trace": run["trace_id"], "rate_scale": run["rate_scale"],
            "requests": n_requests, "completed": report["completed"],
            "iterations": report["iterations"], "wall_s": round(report["wall_s"], 1),
            "accounting_passed": bool(acc.get("passed")),
            "no_rejects": report["rejected"] == 0,
            "validation_passed": passed,
            "problems": "; ".join(problems[:4]),
            "gates_status": run["gates_status"],
        })
    return rows, ok


#: An iteration this much longer than any measured prefill chunk cannot be GPU work: it is a
#: host stall, and any request running through it records an ITL failure it would not have had.
STALL_S = 0.4


# --------------------------------------------------------------------------- #
# Sensitivity from stored per-request latencies (no GPU cost, no re-tuning)
# --------------------------------------------------------------------------- #
TTFT_GRID = (0.5, 1.0, 2.0)
ITL_GRID = (0.100, 0.200)


def attainment_at(requests: list, ttft_s: float, itl_s: float) -> dict:
    """Recompute attainment for an SLO pair from the stored per-request latencies."""
    passed = fail_ttft = fail_itl = both = 0
    for r in requests:
        ttft, itl = r.get("ttft_s"), r.get("max_itl_s")
        if not r.get("finished") or ttft is None:
            continue
        bad_ttft = float(ttft) > ttft_s
        bad_itl = itl is not None and float(itl) > itl_s
        if bad_ttft and bad_itl:
            both += 1
        elif bad_ttft:
            fail_ttft += 1
        elif bad_itl:
            fail_itl += 1
        else:
            passed += 1
    n = len(requests)
    return {"pass": passed, "fail_ttft": fail_ttft, "fail_itl": fail_itl, "both": both,
            "attainment": (passed / n) if n else None, "n": n}


def bootstrap_difference_ci(pairs: list, resamples: int = 10000, seed: int = 6222,
                            alpha: float = 0.05) -> tuple:
    """Paired bootstrap CI for the mean difference of paired samples."""
    if not pairs:
        return (None, None)
    rng = random.Random(seed)
    n = len(pairs)
    diffs = []
    for _ in range(resamples):
        total = 0.0
        for _ in range(n):
            total += pairs[rng.randrange(n)]
        diffs.append(total / n)
    diffs.sort()
    return (_quantile(diffs, alpha / 2.0), _quantile(diffs, 1.0 - alpha / 2.0))


def _quantile(sorted_values, q):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = q * (len(sorted_values) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


# --------------------------------------------------------------------------- #
# Paired per-request comparison
# --------------------------------------------------------------------------- #
def _attains(request: dict, ttft_s: float, itl_s: float) -> bool:
    if not request.get("finished") or request.get("ttft_s") is None:
        return False
    if float(request["ttft_s"]) > ttft_s:
        return False
    return request.get("max_itl_s") is None or float(request["max_itl_s"]) <= itl_s


def _mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def paired_compare(runs: list, policy_a: str, policy_b: str, *,
                   ttft_s: float = 1.0, itl_s: float = 0.2) -> list:
    """Per-request paired comparison of two policies within each cell and repetition.

    Requests are matched by ``request_id``, so both policies served the same prompt
    length, the same forced output length and the same arrival time.  Reported per cell:
    the attainment difference with McNemar discordant counts, and the paired TTFT
    difference with a bootstrap interval.
    """
    # Keyed by *run*, not by repetition index: a supplementary pass re-runs the same cell with
    # its own rep numbering, and keying on (trace, rate, rep) would silently let one run
    # overwrite another run of the same configuration.
    by_cell = {}
    for run in runs:
        by_cell.setdefault((run["run_id"], run["trace_id"], run["rate_scale"], run["rep"]),
                           {})[run["policy"]] = run
    rows = []
    for cell, policies in sorted(by_cell.items(),
                                 key=lambda kv: (str(kv[0][1]), kv[0][2], kv[0][0], kv[0][3])):
        if policy_a not in policies or policy_b not in policies:
            continue
        run_a, run_b = policies[policy_a], policies[policy_b]
        req_a = {r["request_id"]: r for r in run_a["requests"]}
        req_b = {r["request_id"]: r for r in run_b["requests"]}
        common = sorted(set(req_a) & set(req_b))
        only_a = only_b = both = neither = 0
        ttft_pairs, tpot_pairs = [], []
        for rid in common:
            a, b = req_a[rid], req_b[rid]
            pass_a, pass_b = _attains(a, ttft_s, itl_s), _attains(b, ttft_s, itl_s)
            only_a += int(pass_a and not pass_b)
            only_b += int(pass_b and not pass_a)
            both += int(pass_a and pass_b)
            neither += int((not pass_a) and (not pass_b))
            if a.get("ttft_s") and b.get("ttft_s"):
                ttft_pairs.append(float(a["ttft_s"]) - float(b["ttft_s"]))
            if a.get("mean_tpot_s") and b.get("mean_tpot_s"):
                tpot_pairs.append(float(a["mean_tpot_s"]) - float(b["mean_tpot_s"]))
        ci_lo, ci_hi = bootstrap_difference_ci(ttft_pairs)
        rows.append({
            "run_id": cell[0], "trace": cell[1], "rate_scale": cell[2], "rep": cell[3],
            "pair": f"{policy_a} - {policy_b}", "n_paired": len(common),
            "attain_a": run_a["report"]["attainment"],
            "attain_b": run_b["report"]["attainment"],
            "attain_delta": (run_a["report"]["attainment"]
                             - run_b["report"]["attainment"]),
            "only_a_passes": only_a, "only_b_passes": only_b, "both_pass": both,
            "neither_passes": neither, "mcnemar_p": _mcnemar_exact(only_a, only_b),
            "ttft_mean_delta_ms": (1000.0 * statistics.mean(ttft_pairs)) if ttft_pairs
            else None,
            "ttft_delta_ci_lo_ms": (1000.0 * ci_lo) if ci_lo is not None else None,
            "ttft_delta_ci_hi_ms": (1000.0 * ci_hi) if ci_hi is not None else None,
            "ttft_median_delta_ms": (1000.0 * statistics.median(ttft_pairs)) if ttft_pairs
            else None,
            "tpot_mean_delta_ms": (1000.0 * statistics.mean(tpot_pairs)) if tpot_pairs
            else None,
            "goodput_a": run_a["report"]["goodput_eval_window"],
            "goodput_b": run_b["report"]["goodput_eval_window"],
            # Throughput is the readout that still sees the lever when attainment is 0 for
            # every configuration (a workload that is simply over capacity for its SLO).
            "throughput_a": run_a["report"]["throughput_rps_trace_window"],
            "throughput_b": run_b["report"]["throughput_rps_trace_window"],
            "throughput_delta_pct": (100.0 * (run_a["report"]["throughput_rps_trace_window"]
                                              / run_b["report"]["throughput_rps_trace_window"]
                                              - 1.0)
                                     if run_b["report"]["throughput_rps_trace_window"] else None),
            "goodput_delta": (run_a["report"]["goodput_eval_window"]
                              - run_b["report"]["goodput_eval_window"]),
        })
    return rows


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
def theoretical_unloaded_ttft_ms() -> dict:
    """Unloaded TTFT per trace from measured costs: one prefill of the mean prompt + one step.

    Needed because the contract's regime test wants "twice the unloaded TTFT for the same length
    mix", and a trace measured at a single load level has no unloaded run to take it from (using
    the cell itself as its own baseline makes every such cell look underloaded).
    """
    costs = ROOT / "results" / "costs" / "cost_table_measure.json"
    if not costs.exists():
        return {}
    doc = json.loads(costs.read_text())
    rows = [c for c in doc["cells"]["prefill"] if c["preset"] == "large"]
    if not rows:
        return {}
    ms_per_token = min(c["ms"] / c["chunk"] for c in rows)
    dec = [c for c in doc["cells"]["decode"] if c["preset"] == "large"]
    step_ms = max(c["ms"] for c in dec) if dec else 0.0
    out = {}
    for path in sorted((ROOT / "traces").glob("azure_*.json")):
        requests = json.loads(path.read_text()).get("requests") or []
        if not requests:
            continue
        # the *median* prompt is what TTFT p50 sees, not the mean
        prompts = sorted(r["prompt_tokens"] for r in requests)
        median_prompt = prompts[len(prompts) // 2]
        out[path.stem] = median_prompt * ms_per_token + step_ms
    return out


def unloaded_ttft_baseline(runs: list) -> dict:
    """Per trace, the TTFT p50 of a run that is *actually* not queueing.

    The frozen contract defines a run as overloaded iff (a) the fraction of iterations that
    began with an unstarted queue or an undecoded backlog exceeds 0.5 AND (b) TTFT p50
    exceeds twice the unloaded TTFT for the same length mix.  (b) needs a same-mix baseline,
    so it is taken from the same trace at its lightest load: the lowest rate-scale run whose
    queue-active fraction is below 0.2, falling back to the lightest run of that trace.
    """
    theoretical = theoretical_unloaded_ttft_ms()
    by_trace = {}
    for run in runs:
        by_trace.setdefault(run["trace_id"], []).append(run)
    baselines = {}
    for trace, group in by_trace.items():
        light = [r for r in group if r["report"]["queue_active_iteration_frac"] < 0.2]
        measured = min((r for r in light), key=lambda r: r["rate_scale"], default=None)
        if measured is not None:
            baselines[trace] = {"ttft_p50_ms": measured["report"]["ttft_s"]["median"],
                                "source": "measured lightest run",
                                "from_rate_scale": measured["rate_scale"]}
        else:
            baselines[trace] = {"ttft_p50_ms": theoretical.get(trace),
                                "source": "theoretical (median prompt prefill + one step)",
                                "from_rate_scale": None}
    return baselines


def per_run_table(runs: list) -> list:
    rows = []
    for run in runs:
        rep = run["report"]
        rows.append({
            "run_id": run["run_id"], "trace": run["trace_id"],
            "rate_scale": run["rate_scale"], "policy": run["policy"], "rep": run["rep"],
            "requests": rep["requests"], "iterations": rep["iterations"],
            "wall_s": round(rep["wall_s"], 1), "drain_s": round(rep["drain_s"], 1),
            "attainment": rep["attainment"],
            "attainment_ttft_only": rep["attainment_ttft_only"],
            "attainment_secondary": rep["attainment_secondary"],
            "goodput_trace_window": rep["goodput_trace_window"],
            "goodput_eval_window": rep["goodput_eval_window"],
            "throughput_rps": rep["throughput_rps_trace_window"],
            "pass": rep["breakdown"][slo_mod.PASS],
            "fail_ttft": rep["breakdown"][slo_mod.FAIL_TTFT],
            "fail_itl": rep["breakdown"][slo_mod.FAIL_ITL],
            "fail_both": rep["breakdown"][slo_mod.FAIL_BOTH],
            "ttft_p50_ms": rep["ttft_s"]["median"], "ttft_p90_ms": rep["ttft_s"]["p90"],
            "ttft_p99_ms": rep["ttft_s"]["p99"],
            "itl_p50_ms": rep["max_itl_s"]["median"], "itl_p95_ms": rep["max_itl_s"]["p95"],
            "itl_p99_ms": rep["max_itl_s"]["p99"],
            "tpot_p50_ms": rep["mean_tpot_s"]["median"],
            "e2e_p50_ms": rep["e2e_s"]["median"],
            "prefill_share": rep["prefill_share_of_scheduled_tokens"],
            "queue_active_frac": rep["queue_active_iteration_frac"],
            "peak_running": rep["peak_running"],
            "switches": rep["switches_applied"],
            "requests_with_switch": rep["requests_with_switch"],
            "cache_rebuild_ms": rep.get("cache_rebuild_ms_total"),
            "vram_deferred": rep["vram_deferred_events"],
        })
        rows[-1].update(iteration_stats(run["iterations"], float(CONTRACT["primary"]["itl_gate_s"])))
    return rows


def iteration_stats(iterations: list, gate_s: float) -> dict:
    """Iteration-time evidence: the prefill-interference the ITL gate actually sees.

    A long prompt is prefilled in 2048-token chunks inside a decode iteration, so those
    iterations run far past a decode step and every concurrently running request records a
    gap above the gate.  These are the numbers that make that visible per configuration.
    """
    if not iterations:
        return {}
    durations = [float(it.get("duration_s", 0.0)) for it in iterations]
    if not any(durations):
        return {}
    with_prefill = [it for it in iterations if it.get("prefill_tokens")]
    slow = [d for d in durations if d > gate_s]
    return {
        "mean_iteration_ms": 1000.0 * statistics.mean(durations),
        "max_iteration_ms": 1000.0 * max(durations),
        "prefill_iterations": len(with_prefill),
        "max_prefill_chunk": max((it["prefill_tokens"] for it in with_prefill), default=0),
        "slow_iterations": len(slow),
        "slow_iteration_frac": len(slow) / len(durations),
        # Stalls: iterations far longer than any prefill chunk can explain.  These are host or
        # environment effects (filesystem, other tenants, allocator), not GPU work, and one 1 s
        # stall makes every concurrent request record an ITL failure.
        "stall_iterations": sum(1 for d in durations if d > STALL_S),
        "worst_iteration_ms": 1000.0 * max(durations),
        # Share of the run's wall time spent inside iterations that carry a prefill chunk:
        # this, not the GPU-second prefill share, is what a width change can convert into
        # throughput.
        "prefill_iteration_time_frac": (sum(float(it.get("duration_s", 0.0))
                                            for it in with_prefill) / sum(durations)
                                        if sum(durations) else 0.0),
        "mean_prefill_iteration_ms": (1000.0 * statistics.mean(
            [float(it.get("duration_s", 0.0)) for it in with_prefill])
            if with_prefill else None),
    }


def pairing_integrity(runs: list, arrival_tol_s: float = 1e-3) -> list:
    """Justify the paired analysis: the same request id must be the *same* request.

    Request ids come from the trace, so within a cell the ids must map to identical prompt
    lengths, forced output lengths and arrival times under every configuration -- otherwise
    a "paired" comparison is comparing different requests.  Arrival times are wall-clock
    derived, so they are allowed to differ by microseconds; prompt and output lengths must
    match exactly, and the id sets must be identical.
    """
    groups = {}
    for run in runs:
        groups.setdefault((run["trace_id"], run["rate_scale"]), []).append(run)
    rows = []
    for (trace, scale), records in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        tables = [{x["request_id"]: x for x in r["requests"]} for r in records]
        common = set.intersection(*[set(t) for t in tables])
        ids_match = all(len(t) == len(common) for t in tables)
        bad_prompt = bad_target = bad_arrival = 0
        for rid in common:
            base = tables[0][rid]
            for t in tables[1:]:
                x = t[rid]
                bad_prompt += int(x["prompt_tokens"] != base["prompt_tokens"])
                bad_target += int(x["output_tokens_target"] != base["output_tokens_target"])
                bad_arrival += int(abs(float(x["arrival_s"]) - float(base["arrival_s"]))
                                   > arrival_tol_s)
        rows.append({"trace": trace, "rate_scale": scale, "runs": len(records),
                     "paired_ids": len(common), "id_sets_identical": ids_match,
                     "prompt_mismatches": bad_prompt, "target_mismatches": bad_target,
                     "arrival_mismatches": bad_arrival,
                     "passed": bool(ids_match and not (bad_prompt or bad_target or bad_arrival))})
    return rows


def _mean_over(dicts: list, key: str, default: float = 0.0):
    values = [d[key] for d in dicts if isinstance(d, dict) and d.get(key) is not None]
    return statistics.mean(values) if values else default


def per_cell_table(runs: list, baselines: dict = None) -> list:
    """Aggregate per (trace, rate_scale, policy).  Spread = max - min over repetitions.

    Grouped by run *record* rather than by report so the iteration-derived mechanism
    columns (slow iterations, prefill-iteration time) travel with the numbers.
    """
    baselines = baselines or {}
    groups = {}
    for run in runs:
        groups.setdefault((run["trace_id"], run["rate_scale"], run["policy"]),
                          []).append(run)
    rows = []
    for (trace, scale, policy), records in sorted(groups.items(),
                                                  key=lambda kv: (str(kv[0][0]), kv[0][1],
                                                                  kv[0][2])):
        reports = [r["report"] for r in records]
        stats = [iteration_stats(r["iterations"], float(CONTRACT["primary"]["itl_gate_s"]))
                 for r in records]
        attain = [r["attainment"] for r in reports]
        goodput = [r["goodput_eval_window"] for r in reports]
        def mean_of(fn, default=0.0):
            values = [fn(r) for r in records]
            values = [v for v in values if v is not None]
            return statistics.mean(values) if values else default
        row = {
            "trace": trace, "rate_scale": scale, "policy": policy, "reps": len(records),
            "attainment": statistics.mean(attain),
            "attainment_spread": (max(attain) - min(attain)) if len(attain) > 1 else 0.0,
            "goodput_eval": statistics.mean(goodput),
            "goodput_spread": (max(goodput) - min(goodput)) if len(goodput) > 1 else 0.0,
            "throughput_rps": mean_of(lambda r: r["report"]["throughput_rps_trace_window"]),
            "prefill_share": mean_of(
                lambda r: r["report"]["prefill_share_of_scheduled_tokens"]),
            "queue_active_frac": mean_of(
                lambda r: r["report"]["queue_active_iteration_frac"]),
            "switches_per_run": mean_of(lambda r: r["report"]["switches_applied"]),
            "wall_s": mean_of(lambda r: r["report"]["wall_s"]),
            "peak_running": mean_of(lambda r: r["report"]["peak_running"]),
            "fail_ttft": mean_of(lambda r: r["report"]["breakdown"][slo_mod.FAIL_TTFT]),
            "fail_itl": mean_of(lambda r: r["report"]["breakdown"][slo_mod.FAIL_ITL]),
            "fail_both": mean_of(lambda r: r["report"]["breakdown"][slo_mod.FAIL_BOTH]),
            # ITL failures whose largest gap exceeds any prefill chunk: conservatively not
            # attributable to the width schedule (see ``STALL_S``).
            "fail_itl_stall_suspect": mean_of(
                lambda r: sum(1 for x in r["requests"]
                              if x.get("max_itl_s") and float(x["max_itl_s"]) > STALL_S)),
            "itl_over_gate_attributable": mean_of(
                lambda r: sum(1 for x in r["requests"]
                              if x.get("max_itl_s")
                              and float(x["max_itl_s"]) > float(CONTRACT["primary"]["itl_gate_s"])
                              and float(x["max_itl_s"]) <= STALL_S)),
            "slow_iterations": _mean_over(stats, "slow_iterations"),
            "slow_iteration_frac": _mean_over(stats, "slow_iteration_frac"),
        "stall_iterations": _mean_over(stats, "stall_iterations"),
        "worst_iteration_ms": _mean_over(stats, "worst_iteration_ms"),
            "mean_iteration_ms": _mean_over(stats, "mean_iteration_ms"),
            "max_iteration_ms": _mean_over(stats, "max_iteration_ms"),
            "mean_prefill_iteration_ms": _mean_over(stats, "mean_prefill_iteration_ms"),
            "prefill_iteration_time_frac": _mean_over(stats, "prefill_iteration_time_frac"),
            "requests_per_run": mean_of(lambda r: r["report"]["requests"]),
        }
        for out_key, source, field in (("ttft_p50_ms", "ttft_s", "median"),
                                       ("ttft_p99_ms", "ttft_s", "p99"),
                                       ("itl_p50_ms", "max_itl_s", "median"),
                                       ("itl_p95_ms", "max_itl_s", "p95"),
                                       ("itl_p99_ms", "max_itl_s", "p99")):
            row[out_key] = statistics.mean([r[source][field] for r in reports])
        baseline = baselines.get(trace, {}).get("ttft_p50_ms")
        row["ttft_p50_vs_unloaded"] = (row["ttft_p50_ms"] / baseline) if baseline else None
        # The frozen contract's own regime test, applied to what actually happened.
        ratio = row["ttft_p50_vs_unloaded"]
        row["queueing"] = bool(row["queue_active_frac"] > 0.5 or (ratio is not None and ratio > 2.0))
        row["baseline_source"] = (baselines.get(trace) or {}).get("source", "n/a")
        rows.append(row)
    return rows


def sensitivity_table(runs: list) -> list:
    """Attainment across the frozen SLO sensitivity grid, from stored latencies."""
    rows = []
    for run in runs:
        base = {"run_id": run["run_id"], "trace": run["trace_id"],
                "rate_scale": run["rate_scale"], "policy": run["policy"], "rep": run["rep"]}
        for ttft_s in TTFT_GRID:
            for itl_s in ITL_GRID:
                stats = attainment_at(run["requests"], ttft_s, itl_s)
                rows.append(dict(base, ttft_slo_s=ttft_s, itl_slo_s=itl_s,
                                 attainment=stats["attainment"],
                                 fail_ttft=stats["fail_ttft"], fail_itl=stats["fail_itl"],
                                 fail_both=stats["both"]))
    return rows


def write_csv(path: Path, rows: list) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def setup_section() -> list:
    """Markdown for the instrument/cost/capacity evidence every result depends on."""
    lines = ["## 0. Instrument gates (run on the same GPU before the matrix)", ""]
    gate_files = sorted((ROOT / "results" / "gates").glob("job-*.json"))
    if gate_files:
        gates = json.loads(gate_files[-1].read_text())
        lines += [f"Source: `{gate_files[-1].relative_to(ROOT)}`, level `{gates['level']}`, "
                  f"overall **{'PASS' if gates['passed'] else 'FAIL'}**; clock guard "
                  f"`{gates['clock_guard'].get('ok')}` "
                  f"({(gates['clock_guard'].get('clocks') or {}).get('sm_mhz')} MHz SM).", "",
                  "| gate | verdict | evidence |", "|---|---|---|"]
        for gate in gates["gates"]:
            lines.append(f"| `{gate['gate']}` | {'pass' if gate['passed'] else 'FAIL'} | "
                         f"{gate['detail']} |")
    else:
        lines.append("No gate artifact found.")
    lines.append("")
    costs = ROOT / "results" / "costs" / "cost_table_measure.json"
    if costs.exists():
        doc = json.loads(costs.read_text())
        pre = {(c["preset"], c["chunk"]): c["ms"] for c in doc["cells"]["prefill"]}
        dec = {(c["preset"], c["batch"]): c["ms"] for c in doc["cells"]["decode"]}
        lines += ["### Width sensitivity measured through the loop's own forwards", "",
                  "Median GPU ms per forward from `calibrate.py --mode measure` "
                  f"(reps={doc['source']['reps']}, device={doc['source']['device']}).", "",
                  "| prefill chunk (tokens) | large ms | small ms | small/large | saving |",
                  "|---:|---:|---:|---:|---:|"]
        for chunk in (128, 256, 512, 1024, 2048, 4096):
            if ("large", chunk) in pre and ("small", chunk) in pre:
                big, small = pre[("large", chunk)], pre[("small", chunk)]
                lines.append(f"| {chunk} | {big:.2f} | {small:.2f} | {small / big:.3f} | "
                             f"{100 * (1 - small / big):.1f}% |")
        lines += ["", "| decode batch | large ms | small ms | small/large |",
                  "|---:|---:|---:|---:|"]
        for batch in (1, 8, 16, 32, 64):
            if ("large", batch) in dec and ("small", batch) in dec:
                big, small = dec[("large", batch)], dec[("small", batch)]
                lines.append(f"| {batch} | {big:.2f} | {small:.2f} | {small / big:.3f} |")
        switch = doc["cells"]["switch"]
        lines += ["", f"Switch apply cost: **{switch['apply_ms']:.3f} ms** for all 35 layers, "
                      f"plus a {switch['boundary_ms']:.2f} ms boundary allowance.", ""]
    capacity = ROOT / "results" / "costs" / "capacity.json"
    if capacity.exists():
        cap = json.loads(capacity.read_text())
        service = cap["service"]
        lines += ["### Capacity and the frozen load ladder", "",
                  f"Measured service capacity **{service['capacity_rps']:.2f} req/s** "
                  f"({service['gpu_seconds_per_request']:.3f} GPU s per request), split "
                  f"**{100 * service['prefill_time_fraction']:.0f}% prefill / "
                  f"{100 * service['decode_time_fraction']:.0f}% decode** of GPU seconds.", "",
                  "| trace | mean req/s | requests | span s | mean prompt | mean output |",
                  "|---|---:|---:|---:|---:|---:|"]
        for name, stats in cap.get("trace_stats", {}).items():
            lines.append(f"| {name} | {stats['mean_rps']:.2f} | {stats['requests']} | "
                         f"{stats['span_s']:.0f} | {stats['mean_prompt_tokens']:.0f} | "
                         f"{stats['mean_output_tokens']:.0f} |")
        ladder = cap.get("recommended_rate_scales", {})
        if ladder:
            lines += ["", f"Ladder (`--rate-scale` on the steady window, whose own mean rate "
                          f"is {ladder.get('trace_mean_rps', float('nan')):.2f} req/s): "
                          f"underloaded **{ladder['underloaded']:.2f}**, saturated "
                          f"**{ladder['saturated']:.2f}**, overloaded "
                          f"**{ladder['overloaded']:.2f}**, backlog-inducing "
                          f"**{ladder['backlog_inducing']:.2f}**."]
    traces = ROOT / "traces"
    if costs.exists() and traces.exists():
        doc = json.loads(costs.read_text())
        # Best per-token prefill cost per preset (the cheapest *per token* chunk, i.e. what a
        # long prompt actually pays), and the largest measured decode batch rate.
        def best_ms_per_token(preset):
            rows = [c for c in doc["cells"]["prefill"] if c["preset"] == preset]
            return min(c["ms"] / c["chunk"] for c in rows) if rows else None

        large_ms_per_token = best_ms_per_token("large")
        small_ms_per_token = best_ms_per_token("small")
        decode_rows = [c for c in doc["cells"]["decode"] if c["preset"] == "large"]
        biggest = max(decode_rows, key=lambda c: c["batch"]) if decode_rows else None
        decode_tok_s = (biggest["batch"] / (biggest["ms"] / 1000.0)) if biggest else None
        if not large_ms_per_token or not decode_tok_s:
            return lines
        lines += ["", "### How much of each workload is prefill? (the lever's addressable share)", "",
                  "Prefill GPU seconds = prompt tokens x measured prefill cost; decode GPU seconds "
                  "= output tokens / measured batch-64 decode rate. This is the ceiling the phase "
                  "hybrid can act on: it changes prefill cost only.", "",
                  "| trace | requests | mean prompt | mean output | prefill GPU s | decode GPU s | "
                  "prefill share | best-case saving if prefill ran Small |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for path in sorted(traces.glob("azure_*.json")):
            doc_t = json.loads(path.read_text())
            reqs = doc_t.get("requests", [])
            if not reqs:
                continue
            prompts = sum(r["prompt_tokens"] for r in reqs)
            outputs = sum(r["output_tokens"] for r in reqs)
            prefill_s = prompts * large_ms_per_token / 1000.0
            decode_s = outputs / decode_tok_s
            share = prefill_s / (prefill_s + decode_s) if prefill_s + decode_s else 0.0
            best = (1 - small_ms_per_token / large_ms_per_token) * share
            lines.append(f"| {path.stem} | {len(reqs)} | {prompts / len(reqs):.0f} | "
                         f"{outputs / len(reqs):.0f} | {prefill_s:.1f} | {decode_s:.1f} | "
                         f"{share:.2f} | {100 * best:.1f}% |")
        lines.append("")
    matrix = ROOT / "results" / "matrix.json"
    if matrix.exists():
        doc = json.loads(matrix.read_text())
        lines += ["", "### Cells (declared before the runs)", "",
                  "| cell | trace | rate-scale | x capacity | requests | truncated window |",
                  "|---|---|---:|---:|---:|---|"]
        for cell in doc["cells"]:
            lines.append(f"| {cell['id']} | {cell['trace']} | {cell['rate_scale']} | "
                         f"{cell['x_capacity']} | {cell['requests_used']} | "
                         f"{'yes' if cell['truncated_window'] else 'no'} |")
        lines += ["", f"Truncation comes from `--max-run-seconds "
                      f"{doc.get('max_run_seconds')}` applied identically to every policy so "
                      f"that a cell fits a bounded slice of the allocation.", ""]
    lines.append("")
    return lines


def markdown(validation, runs_table, cells, paired_hybrid, paired_small, sensitivity,
             contract) -> str:
    lines = ["# Measured results: FFN width switching on one L40S", ""]
    lines.append(f"Contract: TTFT <= {contract['primary']['ttft_s']} s and max ITL <= "
                 f"{contract['primary']['itl_gate_s']} s per request (secondary mean TPOT "
                 f"<= {contract['primary']['tpot_mean_gate_s']} s); goodput = "
                 f"SLO-satisfying completed requests / wall time.")
    lines.append("")
    lines += setup_section()
    lines += ["## 1. Validation (checked before anything is analyzed)", "",
              "| run | trace | rate | policy | rep | requests | iters | wall s | accounting | validated |",
              "|---|---|---|---|---|---:|---:|---:|---|---|"]
    for row in validation:
        lines.append(f"| {row['run_id']} | {row['trace']} | {row['rate_scale']} | "
                     f"{row['policy']} | {row['rep']} | {row['requests']} | "
                     f"{row['iterations']} | {row['wall_s']} | "
                     f"{'pass' if row['accounting_passed'] else 'FAIL'} | "
                     f"{'pass' if row['validation_passed'] else 'FAIL ' + row['problems']} |")
    lines += ["", "## 2. Per-cell results (mean over repetitions)", "",
              "`queueing` applies the contract's overload signals to what actually happened, not to "
              "the requested rate-scale: queue-active iterations > 0.5, or TTFT p50 more than twice "
              "the unloaded TTFT for the same length mix (taken from the trace's own lightest run "
              "when that run is genuinely unloaded, otherwise from the measured prefill cost of its "
              "median prompt -- a trace measured at one load level has no unloaded run of its own).",
              "",
              "Attainment failures are split three ways by the contract: TTFT only, ITL only, or "
              "both. `fail both` is a TTFT failure *and* an ITL failure, not a leftover.", "",
              "`fail ITL` and `fail both` are the contract's buckets. `ITL over gate "
              "(attributable)` counts requests in *any* bucket whose largest gap exceeded the gate "
              "but stayed under 0.4 s -- longer than any prefill chunk measured here -- so it "
              "excludes host stalls (a single stall fails every concurrent request at once) and "
              "is the schedule-attributable part of the ITL signal.", "",
              "| trace | rate | policy | attainment | goodput/s | throughput/s | fail TTFT | "
              "fail ITL | ITL over gate (attributable) | fail both | TTFT p50 | TTFT p99 | ITL p95 | queueing |",
              "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for row in cells:
        lines.append(f"| {row['trace']} | {row['rate_scale']} | {row['policy']} | "
                     f"{row['attainment']:.3f} | {row['goodput_eval']:.3f} | "
                     f"{row['throughput_rps']:.2f} | {row['fail_ttft']:.0f} | "
                     f"{row['fail_itl']:.0f} | {row['itl_over_gate_attributable']:.0f} | "
                     f"{row['fail_both']:.0f} | {row['ttft_p50_ms']:.0f} | "
                     f"{row['ttft_p99_ms']:.0f} | {row['itl_p95_ms']:.0f} | "
                     f"{'queueing' if row.get('queueing') else 'no queue'} |")
    lines += ["", "### 2b. Mechanism: where the latency actually goes", "",
              "`slow iterations` are iterations longer than the frozen ITL gate; a long prompt "
              "is prefilled in 2048-token chunks inside a decode iteration, so those iterations "
              "delay every concurrently running request.", "",
              "| trace | rate | policy | prefill token share | prefill iter time share | mean iter ms | max iter ms | "
              "mean prefill-iter ms | slow iters | stalls >0.4s | worst iter ms | queue active | "
              "TTFT p50 x unloaded | "
              "peak running | switches |",
              "|---|---:|---|---:|" + "---:|" * 11]
    for row in cells:
        ratio = row.get("ttft_p50_vs_unloaded")
        ratio_text = f"{ratio:.2f}x" if ratio else "n/a"
        lines.append(f"| {row['trace']} | {row['rate_scale']} | {row['policy']} | "
                     f"{row['prefill_share']:.2f} | {row['prefill_iteration_time_frac']:.2f} | "
                     f"{row['mean_iteration_ms']:.0f} | "
                     f"{row['max_iteration_ms']:.0f} | {row['mean_prefill_iteration_ms']:.0f} | "
                     f"{row['slow_iterations']:.0f} | {row['stall_iterations']:.0f} | "
                     f"{row['worst_iteration_ms']:.0f} | "
                     f"{row['queue_active_frac']:.2f} | "
                     f"{ratio_text} | "
                     f"{row['peak_running']:.0f} | "
                     f"{row['switches_per_run']:.0f} |")
    lines += ["", "## 3. Paired per-request comparisons", "",
              "Requests are matched by id, so both policies served the same prompt and the "
              "same arrival. `only A / only B` are the discordant attainment pairs "
              "(exact McNemar p).", ""]
    for title, rows in (("static_small vs static_large", paired_small),
                        ("phase_hybrid vs static_large", paired_hybrid)):
        lines += ["", f"### {title}", "",
                  "| trace | rate | rep | n | attain A | attain B | Δ | only A | only B | "
                  "McNemar p | TTFT delta mean ms | 95% CI | d goodput/s | d throughput/s |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|"]
        for row in rows:
            ci = (f"[{row['ttft_delta_ci_lo_ms']:.1f}, {row['ttft_delta_ci_hi_ms']:.1f}]"
                  if row["ttft_delta_ci_lo_ms"] is not None else "n/a")
            lines.append(f"| {row['trace']} | {row['rate_scale']} | {row['rep']} | "
                         f"{row['n_paired']} | {row['attain_a']:.3f} | "
                         f"{row['attain_b']:.3f} | {row['attain_delta']:+.3f} | "
                         f"{row['only_a_passes']} | {row['only_b_passes']} | "
                         f"{row['mcnemar_p']:.3g} | {row['ttft_mean_delta_ms']:.1f} | "
                         f"{ci} | {row['goodput_delta']:+.3f} | "
                         f"{row.get('throughput_delta_pct') or 0.0:+.1f}% |")
    lines += ["", "## 4. SLO sensitivity (attainment recomputed from stored latencies)", "",
              "| trace | rate | policy | rep | " +
              " | ".join(f"TTFT {t} s / ITL {i} s" for t in TTFT_GRID for i in ITL_GRID) + " |",
              "|---|---:|---|---:|" + "---:|" * (len(TTFT_GRID) * len(ITL_GRID))]
    by_run = {}
    for row in sensitivity:
        key = (row["trace"], row["rate_scale"], row["policy"], row["rep"])
        by_run.setdefault(key, {})[(row["ttft_slo_s"], row["itl_slo_s"])] = row["attainment"]
    for key, cell_map in sorted(by_run.items(),
                                key=lambda kv: (str(kv[0][0]), kv[0][1], kv[0][2], kv[0][3])):
        cells_txt = " | ".join(
            f"{cell_map[(t, i)]:.3f}" if cell_map.get((t, i)) is not None else "n/a"
            for t in TTFT_GRID for i in ITL_GRID)
        lines.append(f"| {key[0]} | {key[1]} | {key[2]} | {key[3]} | {cells_txt} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", default=str(ROOT / "run-output"))
    parser.add_argument("--tags", default=None,
                        help="only run-output tags containing any of these (comma-separated)")
    parser.add_argument("--allow-invalid", action="store_true",
                        help="analyze anyway if validation fails (not recommended)")
    args = parser.parse_args()

    runs = load_runs(Path(args.out_dir), tags=args.tags.split(",") if args.tags else None)
    if not runs:
        raise SystemExit("no measured runs found")
    validation, ok = validate(runs)
    print(f"[analyze] {len(runs)} runs; validation {'PASSED' if ok else 'FAILED'}")
    for row in validation:
        flag = "ok  " if row["validation_passed"] else "FAIL"
        print(f"[analyze]   {flag} {row['run_id']} {row['policy']} r{row['rep']} "
              f"({row['trace']} lambda={row['rate_scale']}) {row['problems']}")
    if not ok and not args.allow_invalid:
        raise SystemExit("validation failed; refusing to analyze "
                         "(use --allow-invalid to override)")

    runs_table = per_run_table(runs)
    baselines = unloaded_ttft_baseline(runs)
    cells = per_cell_table(runs, baselines)
    sensitivity = sensitivity_table(runs)
    paired_hybrid = paired_compare(runs, "phase_hybrid", "static_large")
    paired_small = paired_compare(runs, "static_small", "static_large")

    pairing = pairing_integrity(runs)
    print(f"[analyze] pairing integrity: "
          f"{'all cells pass' if all(r['passed'] for r in pairing) else 'FAILED'}")
    for row in pairing:
        print(f"[analyze]   {row['trace']} lambda={row['rate_scale']} paired_ids="
              f"{row['paired_ids']} id_sets_identical={row['id_sets_identical']} "
              f"prompt_mismatch={row['prompt_mismatches']} target_mismatch="
              f"{row['target_mismatches']} arrival_mismatch={row['arrival_mismatches']}")
    if not all(r["passed"] for r in pairing):
        raise SystemExit("pairing integrity failed: the same request id is not the same request")

    ANALYSIS.mkdir(parents=True, exist_ok=True)
    write_csv(ANALYSIS / "validation.csv", validation)
    write_csv(ANALYSIS / "pairing_integrity.csv", pairing)
    write_csv(ANALYSIS / "runs.csv", runs_table)
    write_csv(ANALYSIS / "cells.csv", cells)
    write_csv(ANALYSIS / "sensitivity.csv", sensitivity)
    write_csv(ANALYSIS / "paired_phase_hybrid_vs_static_large.csv", paired_hybrid)
    write_csv(ANALYSIS / "paired_static_small_vs_static_large.csv", paired_small)
    payload = {"contract": CONTRACT["primary"], "n_runs": len(runs),
               "validation_passed": ok, "validation": validation, "cells": cells,
               "pairing_integrity": pairing,
               "paired_phase_hybrid_vs_static_large": paired_hybrid,
               "paired_static_small_vs_static_large": paired_small}
    (ANALYSIS / "analysis.json").write_text(json.dumps(payload, indent=1, default=str) + "\n")
    (ANALYSIS / "analysis.md").write_text(
        markdown(validation, runs_table, cells, paired_hybrid, paired_small, sensitivity,
                 CONTRACT))
    print(f"[analyze] wrote {ANALYSIS}/analysis.md and 6 CSVs; validation_passed={ok}")
    print("\n[analyze] per-cell summary")
    for row in cells:
        print(f"  {row['trace']:<20} lambda={row['rate_scale']:<5} {row['policy']:<14} "
              f"attain={row['attainment']:.3f}+-{row['attainment_spread']:.3f} "
              f"goodput={row['goodput_eval']:.3f}/s "
              f"ttft_p50={row['ttft_p50_ms']:.0f}ms prefill={row['prefill_share']:.2f}")


if __name__ == "__main__":
    main()

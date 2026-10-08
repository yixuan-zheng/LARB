"""SLO contract and goodput accounting for the mixed prefill+decode harness.

The contract (frozen before any policy comparison; see ``results/contract.json``)
------------------------------------------------------------------------------
Primary gate, applied *per request*::

    TTFT <= slo.ttft_s   AND   max inter-token latency <= slo.itl_gate_s

Secondary gate (reported alongside, never a substitute)::

    TTFT <= slo.ttft_s   AND   mean per-token latency (TPOT) <= slo.tpot_mean_gate_s

and a TTFT-only attainment is always reported too, so a binding ITL gate can
never hide a TTFT-side effect (or vice versa).  Goodput is defined as

    completed, quality-eligible, SLO-satisfying requests per unit wall time

with two windows reported: ``trace_window`` (first arrival .. last arrival plus
drain, which is what the Week 1 pilot used) and ``evaluation_window`` (a declared
warm-up removed, ending at the last completion).  The second exists because
dividing by a window that includes an idle tail silently rewards a fast drain.

``latency_math`` (the frozen Week 1 statistics module) is used when it is
importable, so percentiles and summaries are literally the same code; otherwise
an equivalent local fallback keeps this module testable on its own.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

try:  # Week 1 module is stdlib-only; reused verbatim when on PYTHONPATH.
    import latency_math as _lm  # type: ignore
except Exception:  # pragma: no cover - fallback path, exercised by tests
    _lm = None


def stats_backend() -> str:
    return "latency_math" if _lm is not None else "local_fallback"


def quantile(values, q: float) -> float:
    """Linear-interpolation quantile; identical to ``latency_math.quantile``."""
    ordered = sorted(float(v) for v in values)
    if not ordered:
        raise ValueError("empty sample")
    if len(ordered) == 1:
        return float(ordered[0])
    pos = q * (len(ordered) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return float(ordered[lo])
    frac = pos - lo
    return float(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)


def summarize(values) -> dict:
    values = [float(v) for v in values]
    if _lm is not None:
        out = dict(_lm.summarize(values))
    else:  # pragma: no cover - mirrors latency_math.summarize
        ordered = sorted(values)
        n = len(ordered)
        mean = sum(ordered) / n
        var = sum((v - mean) ** 2 for v in ordered) / (n - 1) if n > 1 else 0.0
        std = math.sqrt(var)
        out = {"n": n, "min": ordered[0], "p10": quantile(ordered, 0.10),
               "p25": quantile(ordered, 0.25), "median": quantile(ordered, 0.50),
               "mean": mean, "p75": quantile(ordered, 0.75), "p90": quantile(ordered, 0.90),
               "max": ordered[-1], "std": std, "iqr": quantile(ordered, 0.75) - quantile(ordered, 0.25),
               "cv": (std / mean) if mean else 0.0}
    # p95/p99 are what a tail-sensitive serving claim needs and Week 1's summary
    # stops at p90, so add them here rather than change a frozen module.
    ordered = sorted(values)
    out["p95"] = quantile(ordered, 0.95)
    out["p99"] = quantile(ordered, 0.99)
    return out


# --------------------------------------------------------------------------- #
# Contract
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SLOContract:
    """The frozen primary SLO pair plus the reported alternatives."""

    ttft_s: float = 1.0
    itl_gate_s: float = 0.200
    tpot_mean_gate_s: float = 0.100
    itl_gate_name: str = "max_itl"
    #: Sensitivity grid, reported (not chosen) after the fact.
    ttft_sensitivity_s: tuple = (0.5, 1.0, 2.0)
    itl_sensitivity_s: tuple = (0.100, 0.200)
    #: Quality floor carried from week1/quality; no online per-token penalty.
    quality_floor_pp: float = 5.0
    quality_reference: str = "static_large"
    quality_eligibility: str = "deferred_to_week1_quality_schedules"

    def label(self) -> str:
        return f"ttft{self.ttft_s:.3f}_itl{self.itl_gate_s:.3f}"

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def sensitivity_grid(self) -> list:
        out = []
        for ttft in self.ttft_sensitivity_s:
            for itl in self.itl_sensitivity_s:
                out.append(SLOContract(ttft_s=ttft, itl_gate_s=itl,
                                       tpot_mean_gate_s=self.tpot_mean_gate_s))
        return out


PASS = "pass"
FAIL_TTFT = "fail_ttft"
FAIL_ITL = "fail_itl"
FAIL_BOTH = "fail_ttft+itl"
INCOMPLETE = "incomplete"



# --------------------------------------------------------------------------- #
# Per-request classification
# --------------------------------------------------------------------------- #
def classify(outcome: dict, contract: SLOContract) -> str:
    """Which way a request failed, using the primary gate."""
    if not outcome.get("finished") or outcome.get("ttft_s") is None:
        return INCOMPLETE
    fail_ttft = float(outcome["ttft_s"]) > contract.ttft_s
    fail_itl = outcome.get("max_itl_s") is not None and \
        float(outcome["max_itl_s"]) > contract.itl_gate_s
    if fail_ttft and fail_itl:
        return FAIL_BOTH
    if fail_ttft:
        return FAIL_TTFT
    if fail_itl:
        return FAIL_ITL
    return PASS


def _secondary_pass(outcome: dict, contract: SLOContract) -> bool:
    if not outcome.get("finished") or outcome.get("ttft_s") is None:
        return False
    if contract.tpot_mean_gate_s is not None:
        tpot = outcome.get("mean_tpot_s")
        if tpot is None or float(tpot) > contract.tpot_mean_gate_s:
            return False
    return float(outcome["ttft_s"]) <= contract.ttft_s


def request_rows(outcomes, contract: SLOContract) -> list:
    """Per-request table with the gate verdicts attached (the raw evidence)."""
    rows = []
    for o in outcomes:
        row = {k: v for k, v in o.items() if k != "itl_s"}
        row["verdict"] = classify(o, contract)
        row["primary_pass"] = row["verdict"] == PASS
        row["secondary_pass"] = _secondary_pass(o, contract)
        row["ttft_only_pass"] = bool(o.get("finished") and o.get("ttft_s") is not None
                                     and float(o["ttft_s"]) <= contract.ttft_s)
        row["n_itl"] = len(o.get("itl_s") or [])
        row["p95_itl_s"] = quantile(o["itl_s"], 0.95) if o.get("itl_s") else None
        row["itl_sum_s"] = sum(o.get("itl_s") or [])
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# Aggregate report
# --------------------------------------------------------------------------- #
def summarize_run(state, contract: SLOContract, warmup_s: float = 10.0,
                  wall_s: float | None = None) -> dict:
    """Turn one ``serving_core.RunState`` into the run's SLO/goodput report.

    ``wall_s`` overrides the measured wall time (the replay mode knows its own
    simulated duration).  Attainment is computed over *every* request the trace
    contained, including rejects, so a policy cannot raise attainment by
    refusing work; rejects are also reported separately.
    """
    outcomes = [r.outcome() for r in state.completed] + [r.outcome() for r in state.rejected]
    started = state.completed + state.rejected
    requested_wall = float(wall_s if wall_s is not None else state.wall_s)
    arrivals = [r.arrival_s for r in started]
    finish = [r.finished_s for r in started if r.finished_s is not None]
    first_arrival = min(arrivals) if arrivals else float(state.origin_s)
    drain_end = max(finish) if finish else first_arrival
    eval_start = first_arrival + float(warmup_s)
    trace_wall = max(1e-9, drain_end - first_arrival)
    eval_wall = max(1e-9, drain_end - eval_start)

    counts = {k: 0 for k in (PASS, FAIL_TTFT, FAIL_ITL, FAIL_BOTH, INCOMPLETE)}
    for o in outcomes:
        counts[classify(o, contract)] += 1
    n = len(outcomes)
    primary = counts[PASS]
    secondary = sum(1 for o in outcomes if _secondary_pass(o, contract))
    ttft_only = sum(1 for o in outcomes if o.get("finished") and o.get("ttft_s") is not None
                    and float(o["ttft_s"]) <= contract.ttft_s)
    finished = [o for o in outcomes if o.get("finished") and o.get("ttft_s") is not None]
    in_window = [o for o in outcomes if o.get("arrival_s", 0.0) >= eval_start]
    in_window_pass = sum(1 for o in in_window if classify(o, contract) == PASS)

    def frac(num, denom):
        return (num / denom) if denom else 0.0

    rep = {
        "requests": n,
        "completed": len(state.completed),
        "rejected": len(state.rejected),
        "iterations": state.iteration,
        "wall_s": requested_wall,
        "simulated_wall_s": float(state.wall_s),
        "trace_span_s": float(state.trace_span_s),
        "drain_s": trace_wall,
        "eval_window_s": eval_wall,
        "warmup_s": float(warmup_s),
        "attainment": frac(primary, n),
        "attainment_secondary": frac(secondary, n),
        "attainment_ttft_only": frac(ttft_only, n),
        "attainment_in_window": frac(in_window_pass, len(in_window)),
        "breakdown": counts,
        "breakdown_frac": {k: frac(v, n) for k, v in counts.items()},
        "goodput_trace_window": frac(primary, trace_wall),
        "goodput_eval_window": frac(in_window_pass, eval_wall),
        "throughput_rps_trace_window": frac(len(state.completed), trace_wall),
        "generated_tokens": sum(o.get("output_tokens") or 0 for o in outcomes),
        "prompt_tokens": sum((o.get("prompt_tokens") or 0) for o in outcomes),
        "peak_running": state.peak_running,
        "vram_deferred_events": state.vram_deferred,
        "switches_applied": state.switches_applied,
        "requests_with_switch": sum(1 for o in outcomes if (o.get("switches") or 0) > 0),
        "mean_switches_per_request": frac(sum(o.get("switches") or 0 for o in outcomes), n),
        "queue_active_iteration_frac": _backlog_frac(state),
        "prefill_share_of_scheduled_tokens": _prefill_share(state),
        "padding_waste": _padding_waste(state),
    }
    for key, field in (("ttft_s", "ttft_s"), ("max_itl_s", "max_itl_s"),
                       ("mean_tpot_s", "mean_tpot_s"), ("e2e_s", "e2e_s")):
        vals = [float(o[field]) for o in finished if o.get(field) is not None]
        if vals:
            s = summarize(vals)
            rep[key] = {k: (1000.0 * v if k not in ("n", "cv") else v) for k, v in s.items()}
            rep[key]["unit"] = "ms"
    return rep


def _backlog_frac(state) -> float:
    """Fraction of iterations that began under pressure (either backlog signal).

    A saturated server shows pressure either as requests that have not begun
    prefill (``unstarted``, what TTFT feels) or as ready-to-decode requests that
    did not fit in the decode batch (``decode_backlog``, what ITL feels).  Week 1's
    pilot produced neither, which is why it could not answer the overload question.
    """
    if not state.iterations:
        return 0.0
    loaded = sum(1 for it in state.iterations
                 if it.get("unstarted", 0) > 0 or it.get("decode_backlog", 0) > 0)
    return loaded / len(state.iterations)


def _prefill_share(state) -> float:
    """Share of *scheduled tokens* that were prefill: the lever's exposure."""
    pre = sum(it.get("prefill_tokens", 0) for it in state.iterations)
    dec = sum(it.get("decode_tokens", 0) for it in state.iterations)
    return (pre / (pre + dec)) if (pre + dec) else 0.0


def _padding_waste(state) -> float:
    real = sum(it.get("prefill_tokens", 0) for it in state.iterations)
    padded = sum(it.get("padded_prefill_tokens", 0) for it in state.iterations)
    return ((padded - real) / real) if real else 0.0

    return rows

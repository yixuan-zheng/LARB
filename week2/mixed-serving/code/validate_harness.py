"""Gate suite for the mixed-serving harness: prove the instrument before trusting it.

Modelled on ``week1/latency-baselines/s0_harness_validation.py`` (which proves the
Week 1 instrument resolves a known effect and invents none) and on the S8 gate
(dynamic-at-W == static-at-W).  Each gate answers one question a reader would
otherwise have to take on faith:

===========================  =========================================  =========================
gate                         question                                   pass condition
===========================  =========================================  =========================
``accounting``               does the loop's own bookkeeping add up?    tokens/widths/times exact
``switchable_equals_static`` is the dynamic path the static path?       ``max_abs_logit == 0``
``batch_equivalence``        does padded batched decode equal the       identical token ids
                             per-row reference decode?
``injected_delay``           can the meter see a known delay?           ITL shifts by the injection
``null_diff``                how much does the harness move on its own? measured and bounded
===========================  =========================================  =========================

``null_diff`` is deliberately both a gate and a measurement: the spread it reports is
the harness's own noise floor on this machine, which is what any later goodput
difference has to clear.  Every gate returns a verdict dict and the suite writes one
JSON artifact, so a run can cite the gates it passed.
"""
from __future__ import annotations

import copy
import json
import statistics
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
WEEK1 = ROOT.parent.parent / "week1" / "latency-baselines"
sys.path.insert(0, str(WEEK1))

import latency_lib as lib  # noqa: E402
import policies  # noqa: E402
import serving_core as core  # noqa: E402
import serving_lib as serving  # noqa: E402
import slo as slo_mod  # noqa: E402
import workload  # noqa: E402


def _verdict(name, passed, detail, **extra):
    out = {"gate": name, "passed": bool(passed), "detail": str(detail)}
    out.update(extra)
    return out


def _fresh(executor, config, decode_mode=None):
    """A cheap clone of an executor that shares the model but not the state."""
    clone = copy.copy(executor)
    clone.rows, clone.states, clone.retired_tokens = {}, {}, {}
    clone.controller = executor.controller
    clone.scheduler = core.Scheduler(config)
    clone.cache_rebuild_ms_total = 0.0
    clone.request_index = 0
    if decode_mode:
        clone.decode_mode = decode_mode
    return clone


# --------------------------------------------------------------------------- #
# Accounting invariants (pure function of a completed run)
# --------------------------------------------------------------------------- #
def gate_accounting(state) -> dict:
    """Wrapper over ``serving_core.accounting_check`` (the same check every run gets)."""
    result = core.accounting_check(state)
    return _verdict("accounting", result["passed"],
                    "all per-request and per-iteration invariants hold"
                    if result["passed"] else "; ".join(result["problems"][:5]),
                    n_requests=result["n_requests"], n_iterations=result["n_iterations"],
                    problems=result["problems"])


# --------------------------------------------------------------------------- #
# Dynamic path == static path, and batched decode == per-row decode
# --------------------------------------------------------------------------- #
def gate_switchable_equals_static(executor, static_workers, prompt_len: int = 64) -> dict:
    """``dynamic-at-W`` logits must equal the static worker's, as in Week 1's S8."""
    import dynamic_lib

    ids, _ = lib.build_prompt_ids(executor.tokenizer, prompt_len, offset=0)
    ids = ids.to(executor.device)
    per_preset, problems = {}, []
    with torch.inference_mode():
        for preset, worker in static_workers.items():
            executor.apply_width(preset)
            dynamic_logits = executor.model(input_ids=ids, use_cache=False).logits[:, -1, :]
            static_logits = worker(input_ids=ids, use_cache=False).logits[:, -1, :]
            diff = dynamic_lib.compare_logits(dynamic_logits, static_logits)
            per_preset[preset] = diff
            if diff["max_abs_logit"] > 0.0:
                problems.append(f"{preset}: max_abs_logit {diff['max_abs_logit']}")
    executor.apply_width("large")
    return _verdict("switchable_equals_static", not problems,
                    "dynamic width path is bit-identical to the static workers"
                    if not problems else "; ".join(problems),
                    per_preset=per_preset)


def gate_batch_equivalence(executor, prompt_lengths=(24, 48), output_tokens=3,
                           config=None) -> dict:
    """Padded batched decode must produce the same tokens as one forward per row."""
    config = config or core.EngineConfig(token_budget=64, prefill_token_budget=4096,
                                         decode_batch_cap=8, max_running=8)
    executor.bind(config)
    trace = workload.Trace("gate", [
        {"request_id": f"g{i}", "arrival_s": 0.0, "prompt_tokens": int(pl),
         "output_tokens": int(output_tokens)} for i, pl in enumerate(prompt_lengths)], {})
    contract = slo_mod.SLOContract(ttft_s=1e9, itl_gate_s=1e9)

    def run(decode_mode):
        clone = _fresh(executor, config, decode_mode=decode_mode)
        serving.measured_run(trace, config, policies.build_policy("static_large"),
                             contract, clone, clock=core.WallClock())
        return {rid: list(tokens) for rid, tokens in clone.retired_tokens.items()}

    batched, single = run("batched"), run("single_row")
    problems = [rid for rid in batched
                if batched[rid] != single.get(rid, [])]
    return _verdict("batch_equivalence", not problems and len(batched) == len(prompt_lengths),
                    "batched tokens equal per-row tokens"
                    if not problems else f"mismatched requests: {problems}",
                    batched=batched, single_row=single)


def gate_injected_delay(executor, trace, config, contract, injection_ms=10.0) -> dict:
    """Insert a known delay into the forwards and check the meter sees it.

    Two probes, because they answer different questions:

    * ``inject_all_ms`` delays **every** forward, so every inter-token gap grows by the
      injection and the reported max-ITL must move by ~the injection.  This is the
      assertion.
    * ``inject_decode_ms`` delays only decode steps -- the realistic case, but diluted in
      a median-of-max-gap statistic whenever a prefill gap dominates each request's
      maximum.  Measured and reported, not asserted in both directions.
    """
    def run(**hooks):
        clone = _fresh(executor, config)
        for name, value in hooks.items():
            setattr(clone, name, float(value))
        _state, report = serving.measured_run(
            trace, config, policies.build_policy("static_large"), contract, clone,
            clock=core.WallClock())
        return report

    base = run()
    all_forwards = run(inject_all_ms=injection_ms)
    decode_only = run(inject_decode_ms=injection_ms)
    delta_all = all_forwards["max_itl_s"]["median"] - base["max_itl_s"]["median"]
    delta_decode = decode_only["max_itl_s"]["median"] - base["max_itl_s"]["median"]
    ok = (0.5 * injection_ms) <= delta_all <= (1.5 * injection_ms)
    detail = (f"all-forward injection moved median max-ITL {delta_all:.1f} ms "
              f"(expect ~{injection_ms:.0f} ms); decode-only injection moved it "
              f"{delta_decode:.1f} ms, diluted because each request's largest gap is "
              f"usually the prefill iteration")
    return _verdict("injected_delay", ok, detail,
                    injection_ms=injection_ms, delta_all_ms=delta_all,
                    delta_decode_only_ms=delta_decode,
                    base_median_ms=base["max_itl_s"]["median"],
                    all_median_ms=all_forwards["max_itl_s"]["median"],
                    decode_only_median_ms=decode_only["max_itl_s"]["median"])


# --------------------------------------------------------------------------- #
# Null control: the harness's own noise floor
# --------------------------------------------------------------------------- #
def gate_null_diff(executor, trace, config, contract, reps: int = 2) -> dict:
    """Run the same configuration twice and measure the harness's own spread.

    The decision structure must be *identical* (same iterations, same widths, same
    token counts); only timing may differ, and by how much is the noise floor any
    later goodput difference has to clear (the measured counterpart of Week 1's
    ``null_diff`` instrument check).
    """
    ttfts, itls, structures = [], [], []
    for _ in range(reps):
        clone = _fresh(executor, config)
        state, report = serving.measured_run(
            trace, config, policies.build_policy("static_large"), contract, clone,
            clock=core.WallClock())
        ttfts.append(report["ttft_s"]["median"])
        itls.append(report["max_itl_s"]["median"])
        structures.append([(it["prefill_tokens"], it["decode_tokens"], it["switches"])
                           for it in state.iterations])
    same_structure = all(s == structures[0] for s in structures)
    spread_ttft = (max(ttfts) - min(ttfts)) / max(1e-9, statistics.mean(ttfts))
    spread_itl = (max(itls) - min(itls)) / max(1e-9, statistics.mean(itls))
    ok = same_structure and spread_ttft < 0.5 and spread_itl < 0.5
    return _verdict("null_diff", ok,
                    f"identical schedules; spread {spread_ttft:.1%} TTFT / "
                    f"{spread_itl:.1%} ITL over {reps} runs",
                    ttft_median_ms=ttfts, itl_median_ms=itls,
                    spread_ttft=spread_ttft, spread_itl=spread_itl,
                    identical_schedule=same_structure)


# --------------------------------------------------------------------------- #
# Suite
# --------------------------------------------------------------------------- #
def run_gates(executor, static_workers, *, trace=None, config=None, contract=None,
              level: str = "cheap") -> dict:
    """Run the requested gate level and return one artifact-shaped verdict."""
    config = config or core.EngineConfig(token_budget=256, prefill_token_budget=256,
                                         decode_batch_cap=4, max_running=4)
    contract = contract or slo_mod.SLOContract(ttft_s=1e6, itl_gate_s=1e6)
    gates = [gate_switchable_equals_static(executor, static_workers),
             gate_batch_equivalence(executor, config=config),
             # Prompts **past the sliding window** (512) as well as short ones: the window
             # makes per-layer cache lengths differ, which is where a mask sized from one
             # global length silently breaks.  This is the case that caught exactly that.
             # ... and with a small prefill budget so the *chunked* prefill path is
             # exercised as well (long prompts are split, and a sliding layer's keys then
             # start at a different logical position than a global layer's).
             gate_batch_equivalence(
                 executor, prompt_lengths=(700, 900), output_tokens=3,
                 config=core.EngineConfig(token_budget=512, prefill_token_budget=256,
                                          decode_batch_cap=8, max_running=8))]
    if trace is not None and level != "none":
        gates.append(gate_injected_delay(executor, trace, config, contract))
        if level == "full":
            gates.append(gate_null_diff(executor, trace, config, contract))
    return {"level": level, "passed": all(g["passed"] for g in gates), "gates": gates,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def smoke_trace(prompt_lengths=(24, 48), output_tokens: int = 3, spacing_s: float = 0.05,
                request_prefix: str = "gate"):
    """A short, deterministic trace used for gating (not a workload).

    Built directly from the requested lengths rather than sampled from a Poisson
    process, so a gate can never fail or pass because a random draw produced a
    different number of requests.
    """
    doc = workload.canonical_trace(
        "gate_trace", [i * spacing_s for i in range(len(prompt_lengths))],
        list(prompt_lengths), [int(output_tokens)] * len(prompt_lengths),
        source={"kind": "gate"}, generator={"kind": "deterministic"}, seed=6222)
    for index, req in enumerate(doc["requests"]):
        req["request_id"] = f"{request_prefix}{index:06d}"
    return workload.Trace(doc["trace_id"], doc["requests"], {})


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--level", choices=("cheap", "full", "none"), default="full")
    parser.add_argument("--out", default=str(ROOT / "results" / "gates.json"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--min-sm-clock-mhz", type=float, default=1500.0)
    parser.add_argument("--with-trace", action="store_true",
                        help="include the injected-delay and null-diff gates")
    args = parser.parse_args()

    config = core.EngineConfig(token_budget=256, prefill_token_budget=256,
                               decode_batch_cap=4, max_running=4)
    if str(args.device).startswith("cuda"):
        lib.clock_ramp(2.0)
        clock = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    else:
        clock = {"skipped": True}
    executor, static_workers, _tok, infos = serving.build_executor(
        config, statics=("small",), device=args.device, slice_mode="materialize")
    trace = smoke_trace() if args.with_trace else None
    result = run_gates(executor, static_workers, trace=trace, config=config,
                       level=args.level)
    result["clock_guard"] = clock
    result["worker"] = infos
    result["device"] = args.device
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1) + "\n")
    for gate in result["gates"]:
        print(f"  {'ok  ' if gate['passed'] else 'FAIL'} {gate['gate']}: {gate['detail']}")
    print(f"wrote {path}")
    print("PASS validate_harness" if result["passed"] else "FAIL validate_harness")
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

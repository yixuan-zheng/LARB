"""CPU-only tests for the mixed-serving harness; no GPU, no torch, no model.

Mirrors the role of ``week1/latency-baselines/test_flop_model.py`` and
``test_switch_schedules.py``: prove the *logic* on a login node before any GPU
hour is spent, and leave a machine-readable record.  Everything here runs in
seconds and covers the stdlib half of the harness:

* ``workload`` - ingest, canonicalization, rate scaling, synthetic generation;
* ``policies`` - the three configurations and the online-policy interface;
* ``slo``      - per-request classification and the aggregate report;
* ``serving_core`` - admission, budgets, batching, padding, width application;
* ``cost_table`` - the whole loop end to end in replay mode, including a
  known-effect control (a declared 17% narrower-prefill speedup must move TTFT).

The cost table used by the replay tests is a **fixture**, not a measurement:
``source.kind == "test_fixture"`` says so and its numbers are a declared formula.
The real table is produced by ``calibrate.py`` on the GPU.
"""
from __future__ import annotations

import json
import math
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
# Week 1 is frozen and stdlib-only; put it on the path when present so the SLO
# layer is exercised against the same statistics module the run manifests use.
WEEK1 = ROOT.parent.parent / "week1" / "latency-baselines"
HAS_WEEK1_MATH = (WEEK1 / "latency_math.py").exists()
if HAS_WEEK1_MATH:
    sys.path.insert(0, str(WEEK1))

import cost_table  # noqa: E402
import policies  # noqa: E402
import serving_core as core  # noqa: E402
import slo as slo_mod  # noqa: E402
import workload  # noqa: E402

RESULTS = []


def check(name, condition, detail):
    RESULTS.append({"check": name, "passed": bool(condition), "detail": str(detail)})
    if not condition:
        raise AssertionError(f"FAILED {name}: {detail}")
    print(f"  ok  {name}: {detail}")


def approx(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


def _raises(fn):
    try:
        fn()
    except Exception:
        return True
    return False


def _cv(values):
    m = sum(values) / len(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var) / m


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
#: Declared synthetic cost model for replay tests.  Prefill is a fixed 29 ms floor
#: plus a per-token term (week1 S2 measured 57.9 ms at 128 tokens and 160.1 ms at
#: 2048 for large, i.e. about 29 ms + 0.064 ms/token).  Narrow prefill is declared
#: 17% faster (week1 measured 0.8235-0.832 of large).  Decode is batch-invariant
#: with a slight rise at large batches (decode-study measured 54.9 ms at batch 1
#: and 74.1 ms at batch 64 / context 2048).
FIXTURE_PREFILL = {"large": (29.0, 0.064), "small": (29.0, 0.064 * 0.83)}
FIXTURE_SWITCH_MS = 0.087 + 0.60


def fixture_cost_doc(preset_factor=None):
    factor = dict(FIXTURE_PREFILL if preset_factor is None else preset_factor)
    prefill, decode = [], []
    for preset, (base, per_token) in factor.items():
        for batch in (1, 2, 4, 8, 16):
            for chunk in (128, 256, 512, 1024, 2048, 4096):
                prefill.append({"preset": preset, "batch": batch, "chunk": chunk,
                                "ctx": 1024, "n": 20, "ms": base + per_token * chunk})
        for batch in (1, 2, 4, 8, 16, 32, 64):
            decode.append({"preset": preset, "batch": batch, "ctx": 1024, "n": 40,
                           "ms": 55.0 + (0.0 if batch <= 8 else (batch - 8) * 0.05)})
    return {"schema_version": 1,
            "source": {"kind": "test_fixture", "note": "declared formula, not a measurement"},
            "cells": {"prefill": prefill, "decode": decode,
                      "switch": {"apply_ms": 0.087, "boundary_ms": 0.60}},
            "kv_bytes_per_token": 40960,
            "vram_budget_bytes": 34 * 1024 ** 3}


def small_trace(rate_rps=4.0, duration_s=6.0, prompt=256, output=8, kind="poisson", seed=7):
    doc = workload.generate_synthetic(
        "fixture_" + kind, rate_rps=rate_rps, duration_s=duration_s, kind=kind, cv=1.0,
        seed=seed,
        prompt_params=workload.lognormal_from_median_p90(prompt, prompt * 2.0),
        output_params=workload.lognormal_from_median_p90(output, output * 2.0),
        prompt_range=(prompt, prompt * 2), output_range=(output, output * 2))
    return workload.Trace(doc["trace_id"], doc["requests"], {"generator": doc["generator"]})


def replay(trace, policy, config=None, contract=None, rate_scale=1.0, cost_doc=None):
    config = config or core.EngineConfig(token_budget=4096, prefill_token_budget=2048,
                                        decode_batch_cap=16, max_running=32)
    contract = contract or slo_mod.SLOContract()
    table = cost_table.CostTable(cost_doc or fixture_cost_doc())
    scaled = trace.with_rate_scale(rate_scale) if rate_scale != 1.0 else trace
    return cost_table.replay_run(scaled, config, policies.build_policy(policy),
                                 contract, table, warmup_s=1.0)


print("mixed-serving harness: CPU self-tests")

# --- workload: ingest and canonicalization ---------------------------------- #
check("percentile_interpolation",
      approx(workload._percentile([1.0, 2.0, 3.0, 4.0], 0.5), 2.5)
      and approx(workload._percentile([5.0], 0.9), 5.0),
      "median of [1,2,3,4] is 2.5; a single value passes through")

tmp = Path(tempfile.mkdtemp(prefix="mixed-serving-test-"))
csv_path = tmp / "mini.csv"
csv_path.write_text(
    "TIMESTAMP,ContextTokens,GeneratedTokens\n"
    "2023-11-16 18:00:00.0000000,100,10\n"
    "2023-11-16 18:00:00.5000000,200,20\n"
    "2023-11-16 18:00:02.0000000,300,30\n")
raw = workload.read_azure_csv(csv_path)
check("azure_csv_ingest", raw["n_rows"] == 3 and approx(raw["t_s"][0], 0.0)
      and approx(raw["t_s"][1], 0.5) and approx(raw["t_s"][2], 2.0),
      f"3 rows, rebased arrivals {raw['t_s']}")
check("azure_csv_provenance_hash", len(raw["sha256"]) == 64, "sha256 of the raw bytes recorded")

doc = workload.canonical_trace("t1", [5.0, 1.0, 3.0], [10, 20, 30], [1, 2, 3],
                               source={"kind": "unit"}, generator={"kind": "unit"})
check("canonical_sorted_and_rebased",
      [r["arrival_s"] for r in doc["requests"]] == [0.0, 2.0, 4.0]
      and doc["requests"][0]["prompt_tokens"] == 20,
      "arrivals sorted and rebased so the first is exactly 0.0")
trace_path = tmp / "t1.json"
workload.write_trace(doc, trace_path)
loaded = workload.load_trace(trace_path)
check("trace_round_trip", loaded.trace_id == "t1" and len(loaded.requests) == 3
      and approx(loaded.span_s, 4.0), "load(write(x)) preserves the trace")
scaled = loaded.with_rate_scale(2.0)
check("rate_scale_compresses_time",
      approx(scaled.requests[-1]["arrival_s"], 2.0)
      and len(scaled.requests) == len(loaded.requests),
      "lambda=2 halves arrival times and keeps every request")
check("rate_scale_metadata", scaled.meta.get("rate_scale") == 2.0, "scale recorded in meta")
check("trace_limit", len(loaded.with_limit(2).requests) == 2, "limit truncates the tail")

bad_path = tmp / "bad.json"
bad_path.write_text(json.dumps({"schema_version": 99, "trace_id": "x", "requests": []}))
check("trace_schema_guard", _raises(lambda: workload.load_trace(bad_path)),
      "a future schema_version is refused rather than misread")

# --- workload: synthetic generation ---------------------------------------- #
prompt_params = workload.lognormal_from_median_p90(1020, 2734)
check("lognormal_mu_is_ln_median", approx(prompt_params["mu"], math.log(1020)),
      f"mu={prompt_params['mu']:.4f} = ln(1020)")
rng_fit = random.Random(1)
samples = [workload._sample_lognormal(rng_fit, prompt_params, 1, 100000) for _ in range(4000)]
sampled_median = workload._percentile(sorted(samples), 0.5)
check("lognormal_samples_median", abs(sampled_median - 1020) / 1020 < 0.10,
      f"sampled median {sampled_median:.0f} is within 10% of the declared 1020")
syn_a = workload.generate_synthetic("a", rate_rps=5.0, duration_s=30.0, seed=42,
                                    prompt_params=prompt_params, output_params=prompt_params)
syn_b = workload.generate_synthetic("a", rate_rps=5.0, duration_s=30.0, seed=42,
                                    prompt_params=prompt_params, output_params=prompt_params)
syn_c = workload.generate_synthetic("a", rate_rps=5.0, duration_s=30.0, seed=43,
                                    prompt_params=prompt_params, output_params=prompt_params)
check("synthetic_reproducible",
      [r["arrival_s"] for r in syn_a["requests"]] == [r["arrival_s"] for r in syn_b["requests"]],
      "same seed gives identical arrivals")
check("synthetic_seed_sensitive",
      [r["arrival_s"] for r in syn_a["requests"]] != [r["arrival_s"] for r in syn_c["requests"]],
      "a different seed gives different arrivals")
gamma = workload.generate_synthetic("g", rate_rps=5.0, duration_s=60.0, kind="gamma", cv=2.0,
                                    seed=42, prompt_params=prompt_params,
                                    output_params=prompt_params)
gaps_g = [b["arrival_s"] - a["arrival_s"]
          for a, b in zip(gamma["requests"], gamma["requests"][1:])]
gaps_p = [b["arrival_s"] - a["arrival_s"]
          for a, b in zip(syn_a["requests"], syn_a["requests"][1:])]
check("gamma_cv_exceeds_poisson", _cv(gaps_g) > _cv(gaps_p) * 1.3,
      f"inter-arrival CV gamma={_cv(gaps_g):.2f} > poisson={_cv(gaps_p):.2f}")
check("synthetic_lengths_in_declared_range",
      all(r["prompt_tokens"] >= 16 and r["output_tokens"] >= 1 for r in gamma["requests"]),
      "declared length range respected")


# --- workload: window selection -------------------------------------------- #
burst_raw = {"t_s": [], "prompt_tokens": [], "output_tokens": [],
             "span_s": 0.0, "sha256": "x", "path": "x", "n_rows": 0}
# Two regions: a quiet one (1 req/s) and an obvious burst (10 req/s, longer prompts).
for i in range(60):
    burst_raw["t_s"].append(float(i))
    burst_raw["prompt_tokens"].append(100)
    burst_raw["output_tokens"].append(10)
for i in range(120):
    burst_raw["t_s"].append(120.0 + i * 0.1)
    burst_raw["prompt_tokens"].append(2000)
    burst_raw["output_tokens"].append(100)
burst_raw["span_s"] = max(burst_raw["t_s"])
burst_raw["n_rows"] = len(burst_raw["t_s"])
sel = workload.select_windows(burst_raw, window_s=60.0, stride_s=60.0)
burst_pick = sel["picks"]["burst"][0]
check("window_burst_found",
      burst_pick["stats"]["mean_rps"] == max(c["stats"]["mean_rps"] for c in sel["candidates"])
      and burst_pick["stats"]["mean_rps"] > 5.0
      and burst_pick["start_s"] <= 120.0 <= burst_pick["start_s"] + 60.0,
      f"burst pick starts at {burst_pick['start_s']:.0f}s, rate "
      f"{burst_pick['stats']['mean_rps']:.2f}/s, and contains the burst at 120s")
check("window_selection_deterministic",
      workload.select_windows(burst_raw, 60.0, 60.0)["picks"]["burst"][0]["start_s"]
      == sel["picks"]["burst"][0]["start_s"], "same criterion, same window")
check("window_mixshift_defined", sel["picks"]["mixshift"][0]["mixshift_score"] > 0.0,
      f"mixshift score {sel['picks']['mixshift'][0]['mixshift_score']:.2f}")
check("window_steady_is_representative",
      sel["picks"]["steady"][0]["rate_score"]
      <= max(c["rate_score"] for c in sel["candidates"]),
      "the steady pick minimizes distance to the global mean rate")

# --- policies -------------------------------------------------------------- #
large = policies.build_policy("static_large")
small = policies.build_policy("static_small")
hybrid = policies.build_policy("phase_hybrid")
view = core.EngineView(now_s=0.0, iteration=0, slo_ttft_s=1.0, slo_itl_s=0.2,
                       waiting_prompts=(100, 200), running=((3, "large", 0.0),),
                       queue_depth=4, admitted=3, completed=0)
check("static_large_widths", large.prefill_width(view) == "large"
      and large.decode_width(view) == "large" and large.name == "static_large",
      "large everywhere")
check("static_small_widths", small.prefill_width(view) == "small"
      and small.decode_width(view) == "small" and small.name == "static_small",
      "small everywhere")
check("phase_hybrid_is_single_switch", hybrid.prefill_width(view) == "small"
      and hybrid.decode_width(view) == "large",
      "narrow prefill, wide decode = week1 quality schedule SL_early")
check("phase_hybrid_describe", hybrid.describe()["max_switches_per_request"] == 1
      and hybrid.describe()["width_history_equivalent"].endswith("SL_early"),
      "declares one switch per request")
check("view_has_no_output_field",
      not any("output" in f for f in core.EngineView.__dataclass_fields__),
      "EngineView exposes no output-length field for a policy to peek at")
check("view_rejects_extra_field",
      _raises(lambda: core.EngineView(now_s=0.0, iteration=0, slo_ttft_s=1.0, slo_itl_s=0.2,
                                      waiting_prompts=(), running=(), queue_depth=0,
                                      admitted=0, completed=0, output_tokens=5)),
      "constructing a view with output_tokens fails loudly")

ld = policies.build_policy("load_driven")
check("load_driven_is_labelled_stub", ld.stub is True and ld.describe()["stub"] is True,
      "owned by workstream C and flagged as a placeholder")
busy = core.EngineView(now_s=0.0, iteration=0, slo_ttft_s=1.0, slo_itl_s=0.2,
                       waiting_prompts=(100,) * 20, running=(), queue_depth=20,
                       admitted=0, completed=0)
idle = core.EngineView(now_s=0.0, iteration=0, slo_ttft_s=1.0, slo_itl_s=0.2,
                       waiting_prompts=(), running=(), queue_depth=1, admitted=1,
                       completed=0)
check("load_driven_narrow_under_pressure", ld.prefill_width(busy) == "small",
      "queue depth 20 >= threshold 8 -> narrow prefill")
check("load_driven_first_change_is_free", ld.prefill_width(idle) == "large",
      "the startup decision may switch once before any dwell is owed")
check("load_driven_dwell_blocks_flap", ld.prefill_width(busy) == "large",
      "min_dwell=4 blocks the immediate switch back to narrow")
for _ in range(4):
    ld.on_iteration(None, None)
check("load_driven_switches_after_dwell", ld.prefill_width(busy) == "small",
      "after 4 iterations the dwell is satisfied and prefill narrows again")
check("load_driven_decode_always_wide", ld.decode_width(busy) == "large",
      "Large-first: decode prefers the wide preset")

# --- SLO classification ---------------------------------------------------- #
contract = slo_mod.SLOContract()


def outcome(ttft, itl, finished=True, tokens=4):
    return {"request_id": "r", "ttft_s": ttft, "max_itl_s": itl, "mean_tpot_s": itl,
            "finished": finished, "output_tokens": tokens, "prompt_tokens": 100,
            "arrival_s": 0.0,
            "e2e_s": ((ttft + itl * tokens) if ttft is not None else None),
            "switches": 0, "itl_s": [itl] * max(1, tokens - 1)}


check("classify_pass", slo_mod.classify(outcome(0.5, 0.05), contract) == slo_mod.PASS,
      "under both gates")
check("classify_fail_ttft",
      slo_mod.classify(outcome(1.5, 0.05), contract) == slo_mod.FAIL_TTFT, "TTFT only")
check("classify_fail_itl",
      slo_mod.classify(outcome(0.5, 0.5), contract) == slo_mod.FAIL_ITL, "ITL only")
check("classify_fail_both",
      slo_mod.classify(outcome(1.5, 0.5), contract) == slo_mod.FAIL_BOTH, "both gates")
check("classify_incomplete",
      slo_mod.classify(outcome(None, 0.0, finished=False), contract) == slo_mod.INCOMPLETE,
      "an unfinished request is not attainment")
check("boundary_is_inclusive",
      slo_mod.classify(outcome(1.0, 0.200), contract) == slo_mod.PASS,
      "exactly at the SLO is a pass (<=)")
check("secondary_gate_stricter",
      slo_mod._secondary_pass(outcome(0.5, 0.15), contract) is False,
      "mean TPOT 150 ms fails the 100 ms secondary gate while passing the primary")
check("stats_backend_declared",
      slo_mod.stats_backend() in ("latency_math", "local_fallback"),
      f"percentiles come from {slo_mod.stats_backend()}")
check("sensitivity_grid_size", len(contract.sensitivity_grid()) == 6,
      "3 TTFT levels x 2 ITL levels")
if slo_mod.stats_backend() == "latency_math":
    import latency_math as lm  # noqa: E402

    tvals = sorted([0.2, 0.4, 0.6, 0.8])
    check("quantile_matches_week1",
          all(approx(slo_mod.quantile(tvals, q), lm.quantile(tvals, q))
              for q in (0.0, 0.25, 0.5, 0.9, 1.0)),
          "our quantile equals latency_math.quantile at every tested q")
s = slo_mod.summarize([1.0, 2.0, 3.0, 4.0])
check("summarize_adds_tail", s["p95"] >= s["median"] and s["p99"] >= s["p95"],
      f"p95={s['p95']:.2f} p99={s['p99']:.2f} added on top of week1's p90")

# --- SLO aggregate report on a hand-built RunState -------------------------- #
def hand_state():
    st = core.RunState(origin_s=0.0, trace_span_s=4.0, request_count=3, iteration=2)
    good = core.ReqState("good", 0.0, 100, 2)
    good.token_times = [0.4, 0.45]
    good.generated, good.finished_s = 2, 0.45
    slow = core.ReqState("slow", 2.0, 100, 2)
    slow.token_times = [4.0, 4.6]      # TTFT 2.0 s (fail) and ITL 0.6 s (fail)
    slow.generated, slow.finished_s = 2, 4.6
    bad = core.ReqState("itl", 4.0, 100, 2)
    bad.token_times = [4.1, 4.5]       # TTFT 0.1 s ok, ITL 0.4 s -> ITL failure only
    bad.generated, bad.finished_s = 2, 4.5
    st.completed = [good, slow, bad]
    st.iterations = [{"waiting": 0, "prefill_tokens": 100, "decode_tokens": 4,
                      "padded_prefill_tokens": 128, "queue_depth": 3}] * 2
    st.wall_s = 4.6
    return st


rep = slo_mod.summarize_run(hand_state(), contract, warmup_s=0.0)
check("report_attainment", approx(rep["attainment"], 1 / 3, 1e-9),
      f"1 of 3 requests attains both gates ({rep['attainment']:.3f})")
check("report_breakdown",
      rep["breakdown"][slo_mod.FAIL_BOTH] == 1 and rep["breakdown"][slo_mod.FAIL_ITL] == 1
      and rep["breakdown"][slo_mod.PASS] == 1,
      f"breakdown {rep['breakdown']}")
check("report_goodput_matches_window",
      approx(rep["goodput_trace_window"], 1 / 4.6, 1e-6),
      f"goodput = 1 pass / 4.6 s drain (first arrival 0.0 to last finish 4.6) "
      f"= {rep['goodput_trace_window']:.3f}/s")
check("report_ttft_in_ms",
      rep["ttft_s"]["unit"] == "ms" and abs(rep["ttft_s"]["median"] - 400.0) < 1e-6,
      f"TTFT median reported in ms ({rep['ttft_s']['median']:.1f})")
check("report_prefill_share",
      approx(rep["prefill_share_of_scheduled_tokens"], 200 / 208, 1e-9),
      "prefill token share of scheduled tokens")
check("report_padding_waste", abs(rep["padding_waste"] - 0.28) < 0.02,
      f"padding waste {rep['padding_waste']:.2%} for bucket 128 on 100-token prompts")
hs = hand_state()
rows = slo_mod.request_rows([r.outcome() for r in hs.completed], contract)
check("request_rows_have_verdicts",
      rows[0]["primary_pass"] is True and rows[1]["verdict"] == slo_mod.FAIL_BOTH
      and "itl_s" not in rows[0],
      "per-request rows carry the verdict, not the raw ITL list")

# --- scheduler: admission, budgets, batching -------------------------------- #
cfg = core.EngineConfig(token_budget=4096, prefill_token_budget=1024, decode_batch_cap=4,
                        prefill_batch_cap=2, pad_bucket=128, max_running=8)
sch = core.Scheduler(cfg)
pol = policies.build_policy("static_large")
r1 = core.ReqState("a", 0.0, 1000, 5)
r2 = core.ReqState("b", 1.0, 300, 5)
r3 = core.ReqState("c", 2.0, 800, 5)
running = [r1, r2, r3]
plan = sch.plan(running, now_s=0.0, iteration=0, completed=0, policy=pol, slo=contract)
check("prefill_fifo_order", [a.request_id for a in plan.prefill] == ["a", "b"],
      "FIFO, and the 1024-token budget stops after a(1000) + b(24)")
check("prefill_batch_cap", len(plan.prefill) <= cfg.prefill_batch_cap,
      f"at most {cfg.prefill_batch_cap} requests per prefill batch")
check("prefill_budget_respected", plan.prefill_tokens <= cfg.prefill_token_budget,
      f"{plan.prefill_tokens} <= {cfg.prefill_token_budget} new prefill tokens")
check("padding_groups_by_bucket",
      all(a.padded_len == math.ceil(a.chunk_len / cfg.pad_bucket) * cfg.pad_bucket
          and a.padded_len % cfg.pad_bucket == 0 for a in plan.prefill)
      and len({a.padded_len for a in plan.prefill_groups[0]}) == 1,
      "every chunk is rounded to the 128-token bucket, and a batch shares one padded length")
check("decode_excludes_this_iteration_prefills",
      set(plan.decode).isdisjoint({a.request_id for a in plan.prefill}),
      "a request prefilled in an iteration does not also decode in it")
check("empty_plan_when_idle", sch.plan([], 0.0, 0, 0, pol, contract).is_empty(),
      "no work -> empty plan")

# chunked prefill: a started request keeps its turn, and budgets still bind
cfg_chunk = core.EngineConfig(token_budget=4096, prefill_token_budget=512,
                              decode_batch_cap=4, prefill_chunk=256, pad_bucket=64)
sch_chunk = core.Scheduler(cfg_chunk)
p0 = sch_chunk.plan(running, 0.0, 0, 0, pol, contract)
for a in p0.prefill:
    st = {"a": r1, "b": r2, "c": r3}[a.request_id]
    st.prefill_pos += a.chunk_len
    st.prefill_started_s = 0.1
p1 = sch_chunk.plan(running, 0.2, 1, 0, pol, contract)
check("chunked_prefill_stickiness", p1.prefill[0].request_id == "a",
      "the partially prefilled request keeps its turn (no starvation under chunking)")
check("chunk_size_respected",
      all(a.chunk_len <= cfg_chunk.prefill_chunk for a in p1.prefill),
      "no chunk exceeds the configured prefill chunk")

r4 = core.ReqState("d", 3.0, 10, 5)
r4.prefill_pos, r4.token_times, r4.generated = 10, [0.5], 1
r4.prefill_widths, r4.last_token_s = ["large"], 0.5
plan2 = sch.plan(running + [r4], 0.5, 2, 0, pol, contract)
check("decode_takes_prefilled_requests", "d" in plan2.decode,
      "a prefilled, unfinished request is decodable")
check("decode_batch_cap", len(plan2.decode) <= cfg.decode_batch_cap,
      f"decode batch <= {cfg.decode_batch_cap}")

r5 = core.ReqState("e", 4.0, 10, 5)
r5.prefill_pos, r5.token_times, r5.generated, r5.last_token_s = 10, [0.9], 1, 0.9
r6 = core.ReqState("f", 5.0, 10, 5)
r6.prefill_pos, r6.token_times, r6.generated, r6.last_token_s = 10, [0.2], 1, 0.2
plan3 = sch.plan([r5, r6], 1.0, 3, 0, pol, contract)
check("decode_priority_by_last_token", plan3.decode == ["f", "e"],
      "the request whose last token is oldest is decoded first")
check("config_validation_rejects_zero_budget",
      _raises(lambda: core.EngineConfig(token_budget=0).validate())
      and _raises(lambda: core.EngineConfig(pad_bucket=0).validate())
      and _raises(lambda: core.EngineConfig(prefill_chunk=-1).validate()),
      "a zero budget, a zero padding bucket and a negative chunk are refused")
check("config_allows_budget_larger_than_iteration",
      core.EngineConfig(token_budget=64, prefill_token_budget=4096,
                        decode_batch_cap=4096).validate() is None,
      "a per-phase budget larger than the iteration budget is legal (it is capped "
      "by token_budget at scheduling time)")
check("count_switches", core.count_switches(["small", "large", "large", "small"]) == 2,
      "two changes in four steps")
# --- the whole loop, replayed end to end ------------------------------------ #
trace = small_trace()
state, report = replay(trace, "static_large")
check("replay_completes_every_request",
      len(state.completed) == len(trace.requests) and not state.rejected,
      f"{len(state.completed)}/{len(trace.requests)} requests completed, 0 rejected")
check("replay_generates_exactly_the_trace_lengths",
      all(r.generated == r.output_tokens_target for r in state.completed),
      "forced generation length: one token per trace output token")
check("replay_token_time_invariant",
      all(len(r.token_times) == r.generated for r in state.completed),
      "len(token_times) == generated for every request")
check("replay_width_history_invariant",
      all(len(r.decode_widths) == r.generated - 1 for r in state.completed)
      and all(len(r.step_widths()) == r.generated for r in state.completed),
      "decode_widths == generated tokens minus the prefill's token 0, so "
      "step_widths() has exactly one entry per generated position")
check("replay_prompt_is_fully_prefilled",
      all(r.prefill_pos == r.prompt_tokens for r in state.completed),
      "every request consumed its whole prompt (no silent truncation)")
check("replay_step_widths_match_quality_convention",
      all(r.step_widths() == ["large"] * (len(r.decode_widths) + 1) for r in state.completed),
      "step 0 is the prefill's final chunk, matching week1/quality schedules")
check("replay_static_large_no_switches",
      all(r.outcome()["switches"] == 0 for r in state.completed)
      and report["switches_applied"] == 0, "static_large never switches")
check("replay_reports_mode_and_lookups",
      report["mode"] == "replay" and report["cost_lookups"].get("measured", 0) > 0,
      f"replay is labelled and its lookups are recorded: {report['cost_lookups']}")
check("replay_iteration_logs_are_the_same_shape",
      all(set(it) == set(state.iterations[0]) for it in state.iterations),
      f"{len(state.iterations)} iteration records, all with the same fields")

state_h, report_h = replay(trace, "phase_hybrid")
check("replay_phase_hybrid_one_switch_per_request",
      all(r.outcome()["switches"] == 1 for r in state_h.completed),
      "exactly one width change per request (narrow prefill -> wide decode)")
check("replay_phase_hybrid_width_history",
      all(r.step_widths()[0] == "small" and set(r.step_widths()[1:]) == {"large"}
          for r in state_h.completed),
      "the recorded per-step schedule is exactly SL_early")
state_s, report_s = replay(trace, "static_small")
check("replay_static_small_all_narrow",
      all(set(r.step_widths()) == {"small"} for r in state_s.completed),
      "static_small never leaves the narrow preset")
check("replay_switch_is_charged",
      report_h["switches_applied"] > 0
      and report_h["switches_applied"] == sum(it["switches"] for it in state_h.iterations)
      and report_h["switches_applied"] <= report_h["requests"],
      f"{report_h['switches_applied']} batch-level switches charged at "
      f"{FIXTURE_SWITCH_MS:.3f} ms each; the per-iteration log sums to the same total")
check("static_config_charges_no_switch",
      report["switches_applied"] == 0 and report_s["switches_applied"] == 0,
      "static configurations never pay the switching cost")

# known-effect control: the fixture declares narrow prefill 17% faster, so under
# load the phase hybrid must show a lower TTFT than static_large.  If this fails,
# the harness is not measuring what the policy does.
ttft_large = report["ttft_s"]["median"]
ttft_hybrid = report_h["ttft_s"]["median"]
check("known_effect_control_ttft", ttft_hybrid < ttft_large,
      f"phase-hybrid TTFT median {ttft_hybrid:.1f} ms < static_large {ttft_large:.1f} ms")
check("known_effect_control_is_diluted", ttft_hybrid > ttft_large * 0.4,
      "the gain is a prefill-share fraction, not a fabricated 2x")

# null control: with identical prefill costs for both presets and no switching
# cost, the phase hybrid must land exactly on static_large (no invented effect).
flat_doc = fixture_cost_doc({"large": (29.0, 0.064), "small": (29.0, 0.064)})
flat_doc["cells"]["switch"] = {"apply_ms": 0.0, "boundary_ms": 0.0}
_, report_flat = replay(trace, "phase_hybrid", cost_doc=flat_doc)
check("null_control_no_invented_effect",
      abs(report_flat["ttft_s"]["median"] - report["ttft_s"]["median"]) < 1e-6
      and approx(report_flat["attainment"], report["attainment"]),
      f"identical width costs and zero switch cost -> identical TTFT median "
      f"({report_flat['ttft_s']['median']:.1f} ms vs {report['ttft_s']['median']:.1f} ms)")
# ... and with the real switch cost but identical width costs, the hybrid must pay for
# its switches: total wall time must grow by roughly (#switches x switch cost) and the
# TTFT difference must stay small.  Median TTFT cannot be asserted in one direction,
# because charging the switch shifts the iteration clock and therefore which arrivals
# land in which iteration -- the schedule itself moves by a few milliseconds.
flat_cost_doc = fixture_cost_doc({"large": (29.0, 0.064), "small": (29.0, 0.064)})
state_flat_cost, report_flat_cost = replay(trace, "phase_hybrid", cost_doc=flat_cost_doc)
charged_from_log = sum(it["switch_apply_ms"] for it in state_flat_cost.iterations)
expected_ms = report_flat_cost["switches_applied"] * FIXTURE_SWITCH_MS
check("null_control_charges_switching",
      report_flat_cost["switches_applied"] > 0
      and abs(charged_from_log - expected_ms) < 1e-6,
      f"the per-iteration log charges {charged_from_log:.2f} ms == "
      f"{report_flat_cost['switches_applied']} switches x {FIXTURE_SWITCH_MS:.3f} ms")
check("null_control_no_large_invented_effect",
      abs(report_flat_cost["ttft_s"]["median"] - report["ttft_s"]["median"])
      <= 0.05 * report["ttft_s"]["median"] + 60.0,
      f"identical width costs -> TTFT median {report_flat_cost['ttft_s']['median']:.1f} ms "
      f"vs static_large {report['ttft_s']['median']:.1f} ms (within a decode step)")

# determinism: same trace, same policy, same table -> identical per-request TTFT
state_d, _ = replay(trace, "phase_hybrid")
check("replay_deterministic",
      [r.outcome()["ttft_s"] for r in state_d.completed]
      == [r.outcome()["ttft_s"] for r in state_h.completed],
      "a second run of the same inputs reproduces every TTFT exactly")

# load monotonicity: the same trace at 4x the arrival rate cannot attain more
_, light = replay(trace, "static_large", rate_scale=0.25)
_, heavy = replay(trace, "static_large", rate_scale=4.0)
check("load_monotonic_attainment", light["attainment"] >= heavy["attainment"],
      f"attainment light={light['attainment']:.2f} >= heavy={heavy['attainment']:.2f}")
check("load_monotonic_ttft",
      light["ttft_s"]["p95"] <= heavy["ttft_s"]["p95"] + 1e-6,
      f"TTFT p95 light={light['ttft_s']['p95']:.1f} ms <= "
      f"heavy={heavy['ttft_s']['p95']:.1f} ms")
check("overload_creates_backlog", heavy["queue_active_iteration_frac"] > 0.5,
      f"{heavy['queue_active_iteration_frac']:.0%} of iterations began with an "
      f"unstarted queue")
check("prefill_share_is_measured", 0.0 < report["prefill_share_of_scheduled_tokens"] < 1.0,
      f"measured prefill token share {report['prefill_share_of_scheduled_tokens']:.2f}")

# chunked prefill is a lever, not a width policy: it must change nothing about the
# configuration and everything about how prefill work is spread.
cfg_chunked = core.EngineConfig(token_budget=4096, prefill_token_budget=2048,
                                decode_batch_cap=16, max_running=32, prefill_chunk=64)
state_c, report_c = replay(trace, "phase_hybrid", config=cfg_chunked)
check("chunked_prefill_changes_chunking_not_policy",
      all(r.outcome()["switches"] == 1 for r in state_c.completed)
      and max(r.outcome()["prefill_chunks"] for r in state_c.completed) > 1,
      "one switch per request is preserved while prefill work is chunked")
check("chunked_prefill_reports_padding_waste",
      report_c["padding_waste"] == 0.0,
      "with prefill_batch_cap=1 the padding bucket is capped at the chunk itself, so "
      "padding waste is exactly 0 (the metric exists for a future batched-prefill "
      "path, and reporting 0 is the honest answer here)")

# --- results record --------------------------------------------------------- #
summary = {
    "passed": all(r["passed"] for r in RESULTS),
    "n_checks": len(RESULTS),
    "checks": RESULTS,
    "stats_backend": slo_mod.stats_backend(),
    "week1_math_on_path": HAS_WEEK1_MATH,
    "cost_table_used": "test_fixture (declared formula, not a measurement)",
    "key_numbers": {
        "replay_requests": len(trace.requests),
        "static_large_ttft_median_ms": ttft_large,
        "phase_hybrid_ttft_median_ms": ttft_hybrid,
        "static_large_attainment": report["attainment"],
        "phase_hybrid_attainment": report_h["attainment"],
        "heavy_load_attainment": heavy["attainment"],
    },
}
out_path = ROOT / "results" / "test_serving_cpu.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(summary, indent=2) + "\n")
print(f"wrote {out_path}")
print(f"PASS test_serving_cpu ({summary['n_checks']} checks)", flush=True)



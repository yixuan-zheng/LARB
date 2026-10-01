"""CPU-only sanity tests for ``latency_math``; no GPU, no torch, no model download.

Mirrors the role of ``preflight/code/check_presets.py`` and
``preflight/code/test_tiny_width.py``: a fast, dependency-light check that the analytic
layer is correct before any measurement depends on it. Every expected value below is
hand-derived from the pinned E4B text config so a regression is caught arithmetically
rather than by eyeballing a report.
"""
from __future__ import annotations

import json

import latency_math as lm

RESULTS = []


def check(name, condition, detail):
    RESULTS.append({"check": name, "passed": bool(condition), "detail": detail})
    if not condition:
        raise AssertionError(f"FAILED {name}: {detail}")
    print(f"  ok  {name}: {detail}")


H, LAYERS, Q_HEADS, KV_HEADS, HEAD_DIM = 2048, 35, 8, 2, 256
FULL_W, HALF_W = 16384, 8192
SMALL_WIDTHS = [8192] * 20 + [16384] * 15

print("latency_math self-tests")
spec = lm.ArchSpec.e4b_text()

# --- statistics ------------------------------------------------------------- #
check("quantile_endpoints", lm.quantile([1, 2, 3, 4], 0.0) == 1.0
      and lm.quantile([1, 2, 3, 4], 1.0) == 4.0, "q0/q1 exact")
check("quantile_median", lm.quantile([1, 2, 3, 4], 0.5) == 2.5, "interpolated median 2.5")
check("quantile_matches_statistics",
      abs(lm.quantile([1, 2, 3, 4], 0.25) - 1.75) < 1e-12, "linear interpolation at p25")
s = lm.summarize([1.0, 2.0, 3.0, 4.0])
check("summarize_fields", s["n"] == 4 and s["median"] == 2.5 and s["min"] == 1.0
      and s["max"] == 4.0, f"n/median/min/max = {s['n']}/{s['median']}/{s['min']}/{s['max']}")

# --- paired statistics ------------------------------------------------------ #
large = [100.0 + 0.01 * i for i in range(200)]
small_same = list(large)                       # identical -> must be within noise
null = lm.paired_stats(large, small_same, resamples=2000)
check("paired_null_ratio", abs(null["mean_ratio"] - 1.0) < 1e-9, f"ratio={null['mean_ratio']}")
check("paired_null_ci_contains_one", null["ratio_lo"] <= 1.0 <= null["ratio_hi"],
      f"ci=[{null['ratio_lo']:.4f},{null['ratio_hi']:.4f}]")
check("paired_null_not_appreciable", not null["appreciable"], "identical samples flagged as noise")

faster = [v * 0.75 for v in large]             # 25% faster -> must be detected
real = lm.paired_stats(large, faster, resamples=2000)
check("paired_effect_ratio", abs(real["mean_ratio"] - 0.75) < 1e-9, f"ratio={real['mean_ratio']}")
check("paired_effect_ci_excludes_one", real["ratio_hi"] < 1.0,
      f"ci=[{real['ratio_lo']:.4f},{real['ratio_hi']:.4f}]")
check("paired_effect_appreciable", real["appreciable"], f"verdict={real['verdict']}")
check("paired_speedup_reciprocal", abs(real["speedup"] - 1.0 / 0.75) < 1e-9,
      f"speedup={real['speedup']:.6f}")

# --- least squares ---------------------------------------------------------- #
# T = 0.05 + 2.0 * x  should be recovered exactly from noise-free data.
xs = [1.0, 2.0, 3.0, 4.0, 5.0]
ys = [0.05 + 2.0 * x for x in xs]
fit = lm.linear_fit([[1.0, x] for x in xs], ys)
check("linear_fit_intercept", abs(fit["coef"][0] - 0.05) < 1e-9, f"a={fit['coef'][0]}")
check("linear_fit_slope", abs(fit["coef"][1] - 2.0) < 1e-9, f"b={fit['coef'][1]}")
check("linear_fit_r2", abs(fit["r2"] - 1.0) < 1e-12, f"r2={fit['r2']}")

# --- architecture ----------------------------------------------------------- #
widths = list(spec.widths)
check("layer_types_full_count", spec.layer_types.count("full_attention") == 7
      and spec.layer_types.count("sliding_attention") == 28,
      "7 full / 28 sliding attention layers")
check("kv_owning_layers", len(lm.kv_owning_layers(spec)) == LAYERS - spec.num_kv_shared_layers == 20,
      f"{len(lm.kv_owning_layers(spec))} layers own KV projections")
check("kv_full_length_owners",
      sum(1 for _, store_full in lm.kv_owning_layers(spec) if store_full) == 2,
      "one full-length KV owner per attention type")

# --- cost model: FLOPs ------------------------------------------------------ #
ffn_1 = lm.ffn_flops(spec, widths, 1)
check("ffn_flops_m1", abs(ffn_1 - 6 * H * FULL_W * LAYERS) < 1e-6,
      f"{ffn_1:.0f} FLOP == 6*H*W*layers")
proj_1 = lm.attn_proj_flops(spec, 1)
expected_proj = (20 * 2 * H * (2 * Q_HEADS * HEAD_DIM + 2 * KV_HEADS * HEAD_DIM)
                 + 15 * 2 * H * (2 * Q_HEADS * HEAD_DIM))
check("attn_proj_flops_m1", abs(proj_1 - expected_proj) < 1e-6, f"{proj_1:.0f} FLOP")

steps = lm.flops_per_step(spec, widths, batch=1, q_len=1, ctx_len=2048)
check("ffn_share_dominates", steps["ffn_share"] > 0.85,
      f"FFN is {100 * steps['ffn_share']:.1f}% of linear FLOPs at 2048 ctx")

# Sliding-window layers must attend fewer keys than full layers at long context.
sliding_ctx = 512
long_core = lm.attn_core_flops(spec, 1, 1, 8192)
short_core = lm.attn_core_flops(spec, 1, 1, sliding_ctx)
check("sliding_window_caps_attention", short_core < long_core,
      f"core {short_core:.3e} < {long_core:.3e} at long context")
prefill_causal = lm.attn_core_flops(spec, 1, 512, 512, causal=True)
non_causal = lm.attn_core_flops(spec, 1, 512, 512, causal=False)
check("causal_cheaper_than_full", prefill_causal < non_causal,
      f"causal {prefill_causal:.3e} < full {non_causal:.3e}")

# --- cost model: bytes ------------------------------------------------------ #
small_spec = spec.with_widths(SMALL_WIDTHS)
ffn_large = lm.ffn_weight_bytes(spec, widths, 2)
ffn_small = lm.ffn_weight_bytes(spec, list(small_spec.widths), 2)
check("ffn_bytes_small_over_large", abs(ffn_small / ffn_large - (20 * HALF_W + 15 * FULL_W)
      / (35 * FULL_W)) < 1e-12, f"ratio={ffn_small / ffn_large:.6f} (expected 0.714286)")
check("ffn_bytes_values", ffn_large == 3 * H * 35 * FULL_W * 2 and ffn_small == 3 * H *
      (20 * HALF_W + 15 * FULL_W) * 2, f"large={ffn_large} small={ffn_small}")

parts = lm.weight_bytes(spec, widths, 2)
check("weight_bytes_sum", parts["total"] == (parts["ffn"] + parts["attention"]
      + parts["embeddings"] + parts["other_linear"] + parts["lm_head"]),
      f"total={parts['total'] / 1024**3:.2f} GiB")
# Gemma 3n leaves the output projection untied; omitting it understated the model by 8.5%.
check("lm_head_untied_counted", parts["lm_head"] == H * spec.vocab_size * 2
      and spec.tied_word_embeddings is False,
      f"lm_head {parts['lm_head'] / 1024**3:.2f} GiB, untied")
check("tied_variant_omits_lm_head",
      lm.weight_bytes(spec.with_widths(widths), widths, 2)["lm_head"] > 0,
      "untied default is counted")
check("embeddings_dominate_width_free", parts["embeddings"] > parts["ffn"] * 0.8,
      f"embeddings {parts['embeddings'] / 1024**3:.2f} GiB vs ffn {parts['ffn'] / 1024**3:.2f} GiB")

kv = lm.kv_resident_bytes(spec, 2048, 1, 2)
# 2 full-length owners at 2048 tokens + 18 windowed owners capped at 512, 2 bytes/param,
# 2 KV heads, 256 head_dim, times 2 (keys and values).
expected_kv = (2 * 2048 + 18 * 512) * 2 * KV_HEADS * HEAD_DIM * 2
check("kv_resident_bytes", kv == expected_kv, f"{kv} bytes == {expected_kv}")

# --- utilization helpers ---------------------------------------------------- #
check("mfu_half_peak", abs(lm.mfu(362.05e12, 1.0, 362.05) - 1.0) < 1e-9,
      "full peak at 1 s gives MFU 1.0")
check("bw_utilization", abs(lm.bw_utilization(864e9, 1.0, 864.0) - 1.0) < 1e-9,
      "full peak at 1 s gives 1.0")
check("peaks_table_has_l40s", "NVIDIA L40S" in lm.DEFAULT_PEAKS,
      f"{len(lm.DEFAULT_PEAKS)} device roofs tabulated")

summary = {"passed": all(r["passed"] for r in RESULTS), "n_checks": len(RESULTS),
           "checks": RESULTS,
           "key_numbers": {"ffn_flops_per_token_full_width": ffn_1,
                           "attn_proj_flops_per_token": proj_1,
                           "ffn_bytes_large": ffn_large, "ffn_bytes_small": ffn_small,
                           "weight_bytes_large": parts["total"],
                           "kv_bytes_ctx2048_batch1": kv}}
out_path = __import__("pathlib").Path(__file__).resolve().parent / "results" / "test_flop_model.json"
out_path.parent.mkdir(exist_ok=True)
out_path.write_text(json.dumps(summary, indent=2) + "\n")
print(f"wrote {out_path}")
print("PASS test_flop_model", flush=True)

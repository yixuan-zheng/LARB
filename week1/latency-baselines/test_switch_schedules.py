"""CPU-only sanity tests for ``switch_schedules`` and the width algebra behind it.

No torch, no GPU, no model download: this runs on a login node in a second, the same
bargain ``test_flop_model.py`` makes for ``latency_math``. Every expectation is derived
from the pinned preset counts (small: 20 narrow layers, medium: 10, large: 0) and the
FFN byte identity, so a regression is caught arithmetically rather than by eyeballing a
report.
"""
from __future__ import annotations

import json
from pathlib import Path

import latency_math as lm
import switch_schedules as ss

RESULTS = []


def check(name, condition, detail):
    RESULTS.append({"check": name, "passed": bool(condition), "detail": detail})
    if not condition:
        raise AssertionError(f"FAILED {name}: {detail}")
    print(f"  ok  {name}: {detail}")


print("switch_schedules self-tests")
widths_map = ss.load_preset_widths()

# --- preset plans ----------------------------------------------------------- #
check("presets_loaded", set(widths_map) == set(ss.PRESETS),
      f"{sorted(widths_map)}")
small = ss.WidthPlan.from_preset("small", widths_map)
medium = ss.WidthPlan.from_preset("medium", widths_map)
large = ss.WidthPlan.from_preset("large", widths_map)
check("plan_lengths", all(len(p.widths) == ss.NUM_LAYERS for p in (small, medium, large)),
      f"all {ss.NUM_LAYERS} layers")
check("narrow_layer_counts",
      small.narrow_layers == 20 and medium.narrow_layers == 10 and large.narrow_layers == 0,
      f"small={small.narrow_layers} medium={medium.narrow_layers} large={large.narrow_layers}")
check("large_is_full_width", all(w == ss.WIDTH_FULL for w in large.widths),
      f"every layer {ss.WIDTH_FULL}")
check("presets_monotone", small.summed_width < medium.summed_width < large.summed_width,
      f"{small.summed_width} < {medium.summed_width} < {large.summed_width}")

# --- plan construction / validation ---------------------------------------- #
check("uniform_plan", ss.WidthPlan.uniform(8192).narrow_layers == 0
      and ss.WidthPlan.uniform(8192).summed_width == 8192 * ss.NUM_LAYERS,
      "uniform width has no narrow layers")
check("per_layer_plan", ss.WidthPlan.per_layer("mixed", [8192] * 20 + [16384] * 15).narrow_layers == 20,
      "explicit vector accepted")
bad_length = False
try:
    ss.WidthPlan.uniform(8192, name="bad").widths  # noqa: B018
    ss.WidthPlan("bad", (8192,) * 34)
except ValueError:
    bad_length = True
check("rejects_wrong_length", bad_length, "34 widths rejected")

# --- schedule algebra ------------------------------------------------------- #
plans = ss.schedule_constant("large", 5)
check("constant_length", len(plans) == 5 and all(p.name == "large" for p in plans),
      "5 identical plans")
alt = ss.schedule_alternate("large", "small", 6)
check("alternate_pattern", [p.name for p in alt] == ["large", "small"] * 3,
      "strict alternation")
blk = ss.schedule_block("large", "small", 2, 8)
check("block_pattern", [p.name for p in blk] == ["large", "large", "small", "small"] * 2,
      "block of 2")
rnd_a = ss.schedule_random("large", "small", 100, seed=1)
rnd_b = ss.schedule_random("large", "small", 100, seed=1)
rnd_c = ss.schedule_random("large", "small", 100, seed=2)
check("random_deterministic", [p.name for p in rnd_a] == [p.name for p in rnd_b],
      "same seed -> same schedule")
check("random_seed_sensitive", [p.name for p in rnd_a] != [p.name for p in rnd_c],
      "different seed -> different schedule")
ph = ss.schedule_phase("small", "large", 10, prefill_units=3)
check("phase_pattern", [p.name for p in ph] == ["small"] * 3 + ["large"] * 7,
      "3 prefill units then decode width")

# --- schedule parser -------------------------------------------------------- #
for spec, expect_name in (("const:small", "const_small"),
                          ("alternate:large:small", "alt_large_small"),
                          ("block:large:small:4", "block4_large_small"),
                          ("random:large:small", "rand_large_small"),
                          ("phase:small:large", "phase_small_large"),
                          ("uniform:8192", "uniform8192")):
    name, sched = ss.resolve_schedule(spec, 6)
    check(f"resolve_{spec}", name == expect_name and len(sched) == 6, f"-> {name}")
bad_spec = False
try:
    ss.resolve_schedule("nonsense", 3)
except ValueError:
    bad_spec = True
check("resolve_rejects_unknown", bad_spec, "unknown spec raises")

# --- width-weighted prediction --------------------------------------------- #
per_preset = {"large": 100.0, "small": 80.0}
pred = ss.width_weighted_ms(per_preset, ss.schedule_alternate("large", "small", 4))
check("width_weighted_mean", abs(pred - 90.0) < 1e-9, f"{pred} == (100+80)/2")

# --- interaction with the analytic cost model ------------------------------- #
spec = lm.ArchSpec.e4b_text()
small_spec = spec.with_widths(small.widths)
ffn_large = lm.ffn_weight_bytes(spec, large.widths, 2)
ffn_small = lm.ffn_weight_bytes(small_spec, small.widths, 2)
check("with_widths_accepts_plan", small_spec.widths == small.widths, "plan vector fits ArchSpec")
check("ffn_byte_ratio_small_over_large", abs(ffn_small / ffn_large - 0.714286) < 1e-5,
      f"{ffn_small / ffn_large:.6f} (expected 0.714286)")

summary = {"passed": all(r["passed"] for r in RESULTS), "n_checks": len(RESULTS),
           "checks": RESULTS,
           "key_numbers": {"small_summed_width": small.summed_width,
                           "large_summed_width": large.summed_width,
                           "ffn_byte_ratio_small_over_large": ffn_small / ffn_large}}
out_path = Path(__file__).resolve().parent / "results" / "test_switch_schedules.json"
out_path.parent.mkdir(exist_ok=True)
out_path.write_text(json.dumps(summary, indent=2) + "\n")
print(f"wrote {out_path}")
print("PASS test_switch_schedules", flush=True)

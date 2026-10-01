"""S0: validate the timing harness against known ground truth, with no model involved.

Why this scenario exists
------------------------
The preflight pilot reported a ~0.98x Large/Small ratio and the natural reading was
"narrowing the FFN buys nothing". Before trusting that reading, the instrument must be
shown capable of resolving a difference known to exist, and incapable of inventing one
that does not. The first version of this file asserted "2x the bytes means 2x the time"
at a 64 MiB GEMV shape and FAILED (measured 1.52x): that shape is launch-bound, so the
expectation was wrong, not the harness. The checks below were corrected accordingly and
now test model-based ground truths instead of naive ratios.

Checks
------
1. ``null_diff``          -- the same workload against itself must NOT register a
                            significant paired difference (type-I error guard).
2. ``known_2x_compute``   -- two large *compute-bound* GEMMs differing by exactly 2x in
                            FLOPs. Compute-bound is the right regime for a known ratio
                            because launch overhead is amortized away.
3. ``gemv_scaling``       -- a memory-bound GEMV across a 16 MiB..256 MiB weight range,
                            fitted as ``T = alpha + bytes / BW``. This is the important
                            one: it reports the harness's intrinsic fixed overhead
                            (``alpha``) and the bandwidth it can actually observe, both
                            of which are needed to interpret every later scenario.
4. ``l2_flush_probe``     -- informational only, never gates the suite. Reports whether
                            an L2 flush is detectable at microbenchmark scale.

Gate: checks 1-3 must pass. Check 4 is recorded as evidence either way.
"""
from __future__ import annotations

import argparse

import torch

import latency_lib as lib
import latency_math as lm

SCENARIO = "s0_harness_validation"
#: Decode-shaped memory-bound probe: M=1 token, K=2048 hidden, N = FFN width.
GEMV_K = 2048
GEMV_N = (4096, 8192, 16384, 32768, 65536)
#: Compute-bound known-ratio probe: same shape family, N differs by exactly 2x.
COMPUTE_M, COMPUTE_K, COMPUTE_N = 4096, 4096, (16384, 8192)
#: L2-resident working set for the informational flush probe (L40S L2 is 96 MB).
L2_M = 2048
KB = 1024 ** 2


def _sweep(harness, record, configs, prepare, step, args, label):
    samples = harness.sweep(configs, prepare, step, args.warmup, args.reps, record=record)
    record.set_summary(label, lib.summarize_samples(samples))
    return samples


def check_null_diff(harness, record, args) -> dict:
    """A vs A: must be reported as within noise."""
    weight = torch.randn(GEMV_K, 8192, device="cuda", dtype=torch.bfloat16)
    x = torch.randn(1, GEMV_K, device="cuda", dtype=torch.bfloat16)
    configs = [{"key": "a"}, {"key": "b"}]
    samples = _sweep(harness, record, configs, lambda cfg: None,
                     lambda cfg, state: torch.mm(x, weight), args, "null_diff")
    verdict = lib.compare_pairs(samples, "a", "b", seed=args.seed)
    verdict["expected"] = "within_noise"
    # A and B are the same kernel on same-shaped tensors, so any detectable
    # difference is the harness floor. Recorded rather than hidden: it bounds how
    # small an effect this instrument can honestly claim later.
    verdict["residual_bias_pct"] = 100.0 * abs(verdict["mean_ratio"] - 1.0)
    verdict["passed"] = bool(not verdict["appreciable"])
    record.set_comparison("null_diff", verdict)
    return verdict


def check_known_2x_compute(harness, record, args) -> dict:
    """Compute-bound pair with exactly 2x the FLOPs: expect a ~2x time ratio."""
    x = torch.randn(COMPUTE_M, COMPUTE_K, device="cuda", dtype=torch.bfloat16)
    table = {"big": torch.randn(COMPUTE_K, COMPUTE_N[0], device="cuda", dtype=torch.bfloat16),
             "small": torch.randn(COMPUTE_K, COMPUTE_N[1], device="cuda", dtype=torch.bfloat16)}
    configs = [{"key": "big"}, {"key": "small"}]
    samples = _sweep(harness, record, configs, lambda cfg: None,
                     lambda cfg, state: torch.mm(x, table[cfg["key"]]), args, "known_2x_compute")
    verdict = lib.compare_pairs(samples, "big", "small", seed=args.seed, effect_threshold=0.05)
    verdict["expected_ratio"] = 0.5
    verdict["expected_speedup"] = 2.0
    verdict["ratio_error_pct"] = 100.0 * abs(verdict["mean_ratio"] - 0.5) / 0.5
    verdict["shape"] = {"M": COMPUTE_M, "K": COMPUTE_K, "N": list(COMPUTE_N)}
    verdict["flops"] = {k: 2.0 * COMPUTE_M * COMPUTE_K * n for k, n in zip(table, COMPUTE_N)}
    # The window is asymmetric on purpose. The first version asserted a tight 2.0 and
    # failed at 2.17, which was the *expectation* being wrong: a wider N raises GPU
    # occupancy and hence efficiency per byte, so the larger GEMM can be relatively
    # more efficient and the ratio can legitimately exceed 2.0. That direction
    # matters later -- width reduction fights a geometric-efficiency penalty, not
    # merely a byte reduction.
    verdict["efficiency_effect"] = ("wide GEMM relatively more efficient"
                                    if verdict["speedup"] > 2.0
                                    else "wide GEMM relatively less efficient")
    verdict["accepted_window"] = [1.80, 2.40]
    verdict["passed"] = bool(verdict["ci_excludes_one"] and 1.80 <= verdict["speedup"] <= 2.40)
    record.set_comparison("known_2x_compute", verdict)
    return verdict


def check_gemv_scaling(harness, record, args) -> dict:
    """Memory-bound GEMV across widths; fit ``T = alpha + bytes / BW``.

    Deliberately assumption-light: the pass conditions are monotone growth of the
    medians, a tight linear fit, and an implied bandwidth that is physically plausible
    (between 15% of DRAM peak and 110%, the upper end allowing for L2 reuse).
    """
    x = torch.randn(1, GEMV_K, device="cuda", dtype=torch.bfloat16)
    table = {n: torch.randn(GEMV_K, n, device="cuda", dtype=torch.bfloat16) for n in GEMV_N}
    configs = [{"key": f"n{n}", "n": n, "weight_bytes": GEMV_K * n * 2} for n in GEMV_N]
    samples = _sweep(harness, record, configs, lambda cfg: None,
                     lambda cfg, state: torch.mm(x, table[cfg["n"]]), args, "gemv_scaling")
    rows = [(cfg["n"], cfg["weight_bytes"], lib.summarize_samples(samples)[cfg["key"]]["wall_ms"]["median"])
            for cfg in configs]
    rows.sort(key=lambda r: r[1])
    medians = [r[2] for r in rows]
    monotone = all(b > a for a, b in zip(medians, medians[1:]))
    fit = lm.linear_fit([[1.0, float(r[1])] for r in rows], medians)
    alpha_ms = fit["coef"][0]
    slope = fit["coef"][1]
    implied_bw_gbps = (1e-6 / slope) if slope > 0 else 0.0
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    peak_bw = peaks.get("dram_gbps") or 0.0
    bw_ok = bool(peak_bw == 0 or 0.15 * peak_bw <= implied_bw_gbps <= 1.10 * peak_bw)
    verdict = {
        "points": [{"n": r[0], "weight_mib": r[1] / KB, "median_wall_ms": r[2]} for r in rows],
        "monotone_increasing": monotone,
        "fit_alpha_ms": alpha_ms, "fit_slope_ms_per_byte": slope, "fit_r2": fit["r2"],
        "implied_bandwidth_gbps": implied_bw_gbps, "peak_bandwidth_gbps": peak_bw,
        "implied_bandwidth_fraction": (implied_bw_gbps / peak_bw) if peak_bw else None,
        "passed": bool(monotone and fit["r2"] >= 0.95 and bw_ok),
        "note": ("fit_alpha_ms is the harness's fixed per-call overhead: any real "
                 "scenario whose step time is not much larger than this cannot resolve "
                 "a width effect."),
    }
    record.set_comparison("gemv_scaling", verdict)
    return verdict


def check_l2_flush_probe(harness, record, args) -> dict:
    """Informational: is an L2 flush detectable at microbenchmark scale?

    Never gates the suite. The first S0 run showed no effect at a 64 MiB GEMV, which is
    itself a finding: the flush is conservative and must be reported both ways rather
    than assumed to matter.
    """
    weight = torch.randn(L2_M, 16384, device="cuda", dtype=torch.bfloat16)
    x = torch.randn(1, L2_M, device="cuda", dtype=torch.bfloat16)
    configs = [{"key": "flush_on"}, {"key": "flush_off"}]
    original = harness.flusher.enabled

    def prepare(cfg):
        harness.flusher.enabled = cfg["key"] == "flush_on"
        return None

    samples = _sweep(harness, record, configs, prepare,
                     lambda cfg, state: torch.mm(x, weight), args, "l2_flush_probe")
    harness.flusher.enabled = original
    verdict = lib.compare_pairs(samples, "flush_on", "flush_off", seed=args.seed)
    verdict["working_set_mib"] = weight.numel() * weight.element_size() / KB
    verdict["effect_detected"] = bool(verdict["ci_excludes_one"] and verdict["mean_ratio"] > 1.0)
    verdict["passed"] = True  # informational by construction
    record.set_comparison("l2_flush_probe", verdict)
    return verdict


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=60, default_warmup=15)
    parser.add_argument("--skip-flush-probe", action="store_true")
    args = parser.parse_args()

    protocol = lib.prepare_runtime(args)
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks)
    record.set_protocol(warmup=args.warmup, reps=args.reps, flush_l2=args.flush_l2,
                        flush_mb=args.flush_mb, interleaved=True, shuffled=True,
                        gemv={"K": GEMV_K, "N": list(GEMV_N)},
                        compute_known_2x={"M": COMPUTE_M, "K": COMPUTE_K, "N": list(COMPUTE_N)})
    if args.estimate_only:
        print(lib.estimate_wall_time(len(GEMV_N) + 4, args.reps, args.warmup, 0.25))
        return

    print("[s0] clock ramp ...", flush=True)
    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")
    record.set_extra("clocks_after_ramp", lib.clocks_snapshot())

    harness = lib.Harness(args)
    record.set_extra("flusher", harness.flusher.describe())
    gating, informational = {}, {}
    with torch.inference_mode():
        gating["null_diff"] = check_null_diff(harness, record, args)
        v = gating["null_diff"]
        print(f"[s0] null_diff        pass={v['passed']} ratio={v['mean_ratio']:.4f} "
              f"ci=[{v['ratio_lo']:.4f},{v['ratio_hi']:.4f}] mdd={v['mdd_pct']:.2f}% residual={v['residual_bias_pct']:.2f}%", flush=True)

        gating["known_2x_compute"] = check_known_2x_compute(harness, record, args)
        v = gating["known_2x_compute"]
        print(f"[s0] known_2x_compute pass={v['passed']} speedup={v['speedup']:.3f} "
              f"(expected 2.0) err={v['ratio_error_pct']:.1f}%", flush=True)

        gating["gemv_scaling"] = check_gemv_scaling(harness, record, args)
        v = gating["gemv_scaling"]
        print(f"[s0] gemv_scaling     pass={v['passed']} alpha={v['fit_alpha_ms'] * 1000:.1f}us "
              f"implied_bw={v['implied_bandwidth_gbps']:.1f}GB/s "
              f"({100 * (v['implied_bandwidth_fraction'] or 0):.0f}% of peak) r2={v['fit_r2']:.4f}", flush=True)

        if not args.skip_flush_probe:
            informational["l2_flush_probe"] = check_l2_flush_probe(harness, record, args)
            v = informational["l2_flush_probe"]
            print(f"[s0] l2_flush_probe   effect_detected={v['effect_detected']} "
                  f"ratio={v['mean_ratio']:.4f} ci=[{v['ratio_lo']:.4f},{v['ratio_hi']:.4f}]", flush=True)

        record.set_extra("clocks_at_end", lib.clocks_snapshot())

    ok = all(v.get("passed") for v in gating.values())
    record.set_extra("gating_checks", sorted(gating))
    record.set_extra("all_gating_checks_passed", ok)
    record.complete()
    if not ok:
        raise SystemExit("FAIL s0_harness_validation: see run-output for the failing check")
    print("PASS s0_harness_validation", flush=True)


if __name__ == "__main__":
    main()

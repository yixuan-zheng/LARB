"""Aggregate every scenario record into the latency profile, a CSV and a fitted model.

Reads ``run-output/**/*.json`` (so it works whether the suite wrote flat files or one
subdirectory per preset), then produces:

``results/latency_profile.json``  full aggregated structure
``results/latency_profile.csv``   tidy utilization table, plottable without new deps
``results/comparisons.csv``       every Large-vs-Small verdict with CI and MDD
``results/crossover.json``        fitted cost model + where the width effect exceeds MDD

The fit is the analytical payoff of the whole ladder. For decode and prefill separately
it estimates

    T = a + b * tokens_per_step + c * kv_bytes + d * weight_bytes

by least squares over every measured configuration. ``a`` is the residual host overhead,
``c`` prices width-independent cache traffic and ``d`` prices resident weights -- the one
coefficient that a width change moves. Dividing the measured Large/Small byte difference
by ``d`` gives the *predicted* win, which can be compared against the observed ratio, and
solving ``d * delta_bytes > mdd`` gives the configuration region where the effect is
resolvable in principle.

Deliberately stdlib-only: no pandas, no matplotlib. If a chart is wanted, the CSVs are
importable, and adding a plotting dependency is a decision for the repo owner.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import latency_math as lm

HERE = Path(__file__).resolve().parent
RUN_OUTPUT = HERE / "run-output"
RESULTS = HERE / "results"
PRESETS = ("small", "medium", "large")


METRICS = ("wall_ms", "gpu_ms", "alpha_ms")


def load_records(root: Path) -> list:
    records = []
    for path in sorted(root.rglob("*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001 - a partial file must not kill the report
            print(f"[analyze] skipping unreadable {path.name}: {exc}")
            continue
        if "scenario" in data:
            data["_path"] = str(path)
            records.append(data)
    return records


def preset_of(key: str, record: dict) -> str:
    for preset in PRESETS:
        if key.startswith(preset) or key.endswith(preset):
            return preset
    workers = record.get("workers") or {}
    for preset in PRESETS:
        if preset in workers and key.startswith(preset):
            return preset
    return "unknown"


def weight_bytes_for(record: dict, preset: str):
    workers = record.get("workers") or {}
    entry = workers.get(preset)
    if isinstance(entry, dict):
        total = (entry.get("param_bytes") or {}).get("total")
        if total:
            return total
    manifest = record.get("manifest") or {}
    if manifest.get("preset_used") == preset and manifest.get("preset_widths"):
        spec = lm.ArchSpec.e4b_text().with_widths(manifest["preset_widths"])
        return lm.weight_bytes(spec, list(spec.widths), 2)["total"]
    return None


def flatten(records: list) -> tuple:
    """Return (utilization_rows, comparison_rows)."""
    util_rows, comp_rows = [], []
    for record in records:
        scenario = record.get("scenario", "?")
        preset_used = (record.get("manifest") or {}).get("preset_used")
        blocks = record.get("summary") or {}
        derived = record.get("derived") or {}
        for block, keys in blocks.items():
            if not isinstance(keys, dict):
                continue
            for key, metrics in keys.items():
                if not isinstance(metrics, dict) or "gpu_ms" not in metrics:
                    continue
                preset = preset_of(key, record)
                row = {"scenario": scenario, "block": block, "key": key, "preset": preset,
                       "file": Path(record["_path"]).name, "completed": record.get("completed")}
                for metric in METRICS:
                    entry = metrics.get(metric)
                    if isinstance(entry, dict):
                        row[f"{metric}_median"] = entry.get("median")
                        row[f"{metric}_p90"] = entry.get("p90")
                        row[f"{metric}_cv"] = entry.get("cv")
                        row[f"{metric}_n"] = entry.get("n")
                info = derived.get(key)
                if isinstance(info, dict):
                    for field in ("flops", "bytes_moved_lower_bound", "achieved_bw_gbps",
                                  "bw_utilization", "mfu", "alpha_ms", "kv_resident_bytes",
                                  "tokens_per_step", "prefill_tok_s", "decode_tok_s",
                                  "ffn_flop_share", "batch", "ctx_len", "prompt_len"):
                        if field in info:
                            row[field] = info[field]
                    for field in ("gpu", "wall"):
                        sub = info.get(field)
                        if isinstance(sub, dict):
                            row[f"{field}_mfu"] = sub.get("mfu")
                            row[f"{field}_bw_utilization"] = sub.get("bw_utilization")
                            row[f"{field}_achieved_bw_gbps"] = sub.get("achieved_bw_gbps")
                row["weight_bytes"] = weight_bytes_for(record, preset)
                util_rows.append(row)

        for name, verdict in (record.get("comparisons") or {}).items():
            if not isinstance(verdict, dict) or "mean_ratio" not in verdict:
                continue
            grid = name.rsplit("/", 2)[0] if "/" in name else name
            comp_rows.append({
                "scenario": scenario, "name": name, "grid": grid,
                "file": Path(record["_path"]).name,
                "large_key": verdict.get("large_key"), "small_key": verdict.get("small_key"),
                "metric": verdict.get("metric"), "n": verdict.get("n"),
                "ratio": verdict.get("mean_ratio"), "ci_lo": verdict.get("ratio_lo"),
                "ci_hi": verdict.get("ratio_hi"), "speedup": verdict.get("speedup"),
                "mdd_ms": verdict.get("mdd_ms"), "mdd_pct": verdict.get("mdd_pct"),
                "median_delta_pct": verdict.get("median_delta_pct"),
                "ci_excludes_one": verdict.get("ci_excludes_one"),
                "appreciable": verdict.get("appreciable"), "verdict": verdict.get("verdict"),
                "residual_bias_pct": verdict.get("residual_bias_pct"),
            })
    return util_rows, comp_rows


def fit_group(rows: list, label: str) -> dict:
    """Least-squares T = a + b*tokens + c*kv + d*weight_bytes on usable rows."""
    usable = [r for r in rows if r.get("gpu_ms_median") and r.get("tokens_per_step")
              and r.get("weight_bytes")]
    if len(usable) < 4:
        return {"label": label, "fitted": False,
                "reason": f"only {len(usable)} usable rows (need >= 4)"}
    # Candidate regressors, with the intercept always retained. A column that never
    # varies cannot be identified alongside the intercept (batch-1 decode makes
    # tokens_per_step identically 1), and including it produces a singular system
    # rather than a fit. Drop it and say so.
    candidates = (("ms_per_token", lambda r: float(r["tokens_per_step"])),
                  ("ms_per_kv_byte", lambda r: float(r.get("kv_resident_bytes") or 0)),
                  ("ms_per_weight_byte", lambda r: float(r["weight_bytes"])))
    kept, dropped = [], []
    for name, getter in candidates:
        column = [getter(r) for r in usable]
        if len(set(column)) > 1:
            kept.append((name, getter))
        else:
            dropped.append({"name": name, "constant": column[0] if column else None})
    n_coef = 1 + len(kept)
    if len(usable) < n_coef + 1:
        return {"label": label, "fitted": False, "n_rows": len(usable),
                "dropped_collinear": dropped,
                "reason": (f"{len(usable)} rows cannot support a {n_coef}-coefficient fit "
                           f"without being exactly determined; run a wider grid")}
    features = [[1.0] + [getter(r) for _, getter in kept] for r in usable]
    targets = [float(r["gpu_ms_median"]) for r in usable]
    try:
        fit = lm.linear_fit(features, targets)
    except ValueError as exc:
        return {"label": label, "fitted": False, "reason": str(exc),
                "dropped_collinear": dropped}
    coef = dict(zip(["intercept_ms"] + [n for n, _ in kept], fit["coef"]))
    coef.setdefault("ms_per_weight_byte", None)  # consumers must handle a dropped term
    out = {"label": label, "fitted": True, "n_rows": len(usable), "coef": coef,
           "dropped_collinear": dropped, "r2": fit["r2"], "rows": [{k: r.get(k) for k in
                                       ("key", "preset", "block", "gpu_ms_median",
                                        "tokens_per_step", "kv_resident_bytes",
                                        "weight_bytes")} for r in usable]}
    # Price the width change with the fitted marginal cost of a resident byte.
    if coef.get("ms_per_weight_byte") and coef["ms_per_weight_byte"] > 0:
        per_preset = {}
        for preset in PRESETS:
            totals = [r["weight_bytes"] for r in usable if r["preset"] == preset]
            if totals:
                per_preset[preset] = max(totals)
        if "large" in per_preset and "small" in per_preset:
            delta = per_preset["large"] - per_preset["small"]
            predicted = coef["ms_per_weight_byte"] * delta
            baseline = coef["intercept_ms"] + coef.get("ms_per_token", 0.0) + predicted
            out["width_effect"] = {
                "large_weight_bytes": per_preset["large"],
                "small_weight_bytes": per_preset["small"],
                "delta_bytes": delta,
                "predicted_delta_ms": predicted,
                "predicted_ratio_at_batch1": (baseline - predicted) / baseline if baseline else None,
                "predicted_speedup_at_batch1": (baseline / (baseline - predicted)
                                                if baseline > predicted else None),
            }
    return out


def collect_switching(records: list) -> dict:
    """Pull the ``switching`` block out of every dynamic-scenario record.

    The dynamic scenarios (s8-s11) compute their own derived quantities where the data
    lives and store them under a top-level ``switching`` key; this groups them by scenario
    so the report can render them without re-deriving anything. Records without the key
    (the static s0-s7 scenarios) are simply skipped.
    """
    out = {}
    for record in records:
        block = record.get("switching")
        if not isinstance(block, dict):
            continue
        out.setdefault(record.get("scenario", "?"), []).append({
            "file": Path(record["_path"]).name,
            "completed": record.get("completed"),
            "switching": block,
        })
    return out


# --------------------------------------------------------------------------- #
# Per-scenario detail blocks
#
# The utilization/comparison tables above only cover the scenarios that report a
# ``gpu_ms`` timing block (s1, s2, s3, s5, s7). Three decisive shapes fall outside
# them: s4's request-level latency (the numbers a reader would actually quote),
# s6's per-module attribution and the analytic ceiling it implies, and s7's
# memory/capacity/roofline payload beyond its one latency point. Those decide
# conclusions and future work, so they are extracted here into the tracked
# ``results/`` artifacts instead of being left behind in the git-ignored
# ``run-output/``. s0's gate is carried along too: a reader cannot weigh any
# number without knowing the instrument passed its own validation.
# --------------------------------------------------------------------------- #
ATTRIBUTION_TAGS = ("mlp", "self_attn", "altup", "laurel", "per_layer_input",
                    "per_layer_projection", "norm")
MEMORY_BUCKETS = ("embeddings", "embeddings_per_layer", "ffn", "attention",
                  "per_layer_input", "laurel", "altup", "norms", "other")
S4_METRICS = (("ttft_ms", "ttft"), ("itl_ms", "itl"), ("e2e_ms", "e2e"),
              ("prefill_ms", "prefill"))


def record_preset(record: dict) -> str:
    """The preset a one-preset-per-process record was built with."""
    preset = (record.get("manifest") or {}).get("preset_used")
    if preset in PRESETS:
        return preset
    return preset_of("", record)


def _median_of(value):
    """Median of a sample list or of an already-summarized distribution dict."""
    if isinstance(value, dict):
        return value.get("median")
    if isinstance(value, (list, tuple)) and value:
        return lm.summarize(value)["median"]
    return None


def _gib(value):
    return (value / 1024 ** 3) if value is not None else None


def collect_end_to_end(records: list) -> tuple:
    """s4: per-config TTFT/ITL/e2e/throughput, plus cross-process width ratios.

    s4 runs one preset per process (so peak VRAM is not polluted), which means it
    cannot produce the in-process paired verdicts the other static scenarios emit:
    ``derived`` holds the per-step ITL samples instead, and the ratio is computed
    here by joining the same grid across the small/medium/large files. The result
    is flagged ``interleaved: False`` because the pairing assumption the bootstrap
    wants (interleaved sampling order) does not hold across processes.
    """
    rows, comps, by_grid = [], [], {}
    for record in records:
        if record.get("scenario") != "s4_end_to_end":
            continue
        file = Path(record["_path"]).name
        peak = record.get("peak_memory") or {}
        for key, entry in sorted((record.get("derived") or {}).items()):
            if not isinstance(entry, dict) or "ttft_ms" not in entry:
                continue
            grid = key.split("_", 1)[1] if "_" in key else key
            preset = entry.get("preset") or preset_of(key, record)
            row = {"scenario": "s4_end_to_end", "key": key, "grid": grid, "preset": preset,
                   "batch": entry.get("batch"), "prompt_len": entry.get("prompt_len"),
                   "new_tokens": entry.get("new_tokens"),
                   "generations": entry.get("generations"),
                   "decode_tok_s": entry.get("decode_tok_s"),
                   "e2e_tok_s": entry.get("e2e_tok_s"),
                   "peak_alloc_gib": _gib(peak.get("peak_allocated_bytes")),
                   "file": file, "completed": record.get("completed")}
            for metric, name in S4_METRICS:
                dist = entry.get(metric)
                row[f"{name}_ms_median"] = _median_of(dist)
                row[f"{name}_ms_p90"] = (dist or {}).get("p90") if isinstance(dist, dict) else None
                row[f"{name}_ms_cv"] = (dist or {}).get("cv") if isinstance(dist, dict) else None
            rows.append(row)
            by_grid.setdefault(grid, {})[preset] = (entry, file)
    for grid in sorted(by_grid):
        large, large_file = by_grid[grid].get("large", (None, None))
        if not large:
            continue
        for preset in ("medium", "small"):
            small, small_file = by_grid[grid].get(preset, (None, None))
            if not small:
                continue
            left = large.get("per_step_wall_ms") or []
            right = small.get("per_step_wall_ms") or []
            n = min(len(left), len(right))
            if n < 2:
                continue
            comps.append({"scenario": "s4_end_to_end", "grid": grid, "preset": preset,
                          "metric": "itl_wall_ms", "interleaved": False,
                          "large_file": large_file, "small_file": small_file,
                          **lm.paired_stats(left[:n], right[:n])})
    return rows, comps


def collect_attribution(records: list) -> list:
    """s6: per-module time shares, the ceiling it implies, and the kernel view.

    The ceiling is the load-bearing number: it caps every other scenario's
    achievable width win, so it belongs in the report rather than only in the raw
    record.
    """
    rows = []
    for record in records:
        if record.get("scenario") != "s6_layer_profile":
            continue
        attribution = record.get("attribution") or {}
        sources = (("module", attribution), ("kernel", attribution.get("profiler") or {}))
        for view, source in sources:
            for regime in ("prefill", "decode"):
                block = source.get(regime)
                if not isinstance(block, dict):
                    continue
                shares = block.get("per_tag_share") or block.get("category_share") or {}
                row = {"scenario": "s6_layer_profile", "view": view, "regime": regime,
                       "preset": record_preset(record), "file": Path(record["_path"]).name,
                       "completed": record.get("completed"),
                       "step_gpu_ms": block.get("step_gpu_ms"),
                       "step_ms_median": _median_of(block.get("step_gpu_ms_samples")),
                       "total_cuda_ms": block.get("total_cuda_ms"),
                       "ffn_ms": block.get("ffn_total_ms"),
                       "attributed_ms": block.get("attributed_total_ms"),
                       "ffn_share_attributed": block.get("ffn_time_share"),
                       "ffn_share_of_step": block.get("ffn_time_share_of_step"),
                       "width_reduction_fraction": block.get("width_reduction_fraction"),
                       "in_scope_fraction": block.get("in_scope_fraction"),
                       "ceiling_speedup": block.get("ceiling_speedup_if_ffn_free_portion")}
                for tag, share in shares.items():
                    row[f"share_{tag}"] = share
                rows.append(row)
    return rows


def collect_memory(records: list) -> list:
    """s7: resident weights per bucket, KV per token, capacity cap and roofline."""
    rows = []
    for record in records:
        if record.get("scenario") != "s7_memory_roofline":
            continue
        memory = record.get("memory") or {}
        measured = memory.get("measured_bytes") or {}
        peak = record.get("peak_memory") or {}
        capacity = record.get("capacity") or {}
        cache = record.get("kv_cache") or {}
        roofline = record.get("roofline") or {}
        row = {"scenario": "s7_memory_roofline", "preset": record_preset(record),
               "file": Path(record["_path"]).name, "completed": record.get("completed"),
               "measured_total_gib": memory.get("measured_total_gib"),
               "analytic_total_gib": memory.get("analytic_total_gib"),
               "analytic_minus_measured_pct": memory.get("analytic_minus_measured_pct"),
               "peak_alloc_gib": _gib(peak.get("peak_allocated_bytes")),
               "kv_bytes_per_token": None, "max_batch_ctx_short": None,
               "max_batch_ctx_long": None}
        for bucket in MEMORY_BUCKETS:
            row[f"weights_{bucket}_gib"] = _gib(measured.get(bucket))
        if cache:
            shortest = min(cache, key=lambda k: int(k))
            row["kv_bytes_per_token"] = (cache[shortest] or {}).get("bytes_per_token")
        if capacity:
            shortest = min(capacity, key=lambda k: int(k))
            longest = max(capacity, key=lambda k: int(k))
            row["max_batch_ctx_short"] = (capacity[shortest] or {}).get("max_batch")
            row["max_batch_ctx_long"] = (capacity[longest] or {}).get("max_batch")
        for regime in ("prefill", "decode"):
            point = roofline.get(regime) or {}
            row[f"achieved_bw_gbps_{regime}"] = point.get("achieved_bw_gbps")
            row[f"bw_utilization_{regime}"] = point.get("bw_utilization")
            row[f"mfu_{regime}"] = point.get("mfu")
            row[f"ffn_flop_share_{regime}"] = point.get("ffn_flop_share")
        rows.append(row)
    order = {preset: i for i, preset in enumerate(PRESETS)}
    rows.sort(key=lambda r: order.get(r["preset"], len(PRESETS)))
    return rows


def collect_gates(records: list) -> list:
    """s0: whether the instrument resolved a known effect and invented none."""
    rows = []
    for record in records:
        if record.get("scenario") != "s0_harness_validation":
            continue
        checks = record.get("gating_checks") or []
        guard = record.get("clock_guard") or {}
        rows.append({"scenario": "s0_harness_validation",
                     "file": Path(record["_path"]).name,
                     "completed": record.get("completed"),
                     "passed": record.get("all_gating_checks_passed"),
                     "n_checks": len(checks), "checks": list(checks),
                     "clock_ok": guard.get("ok")})
    return rows


def scenario_coverage(records: list, sections: dict) -> list:
    """One row per scenario that ran, saying which tables it actually reached.

    Exists so a scenario can never again be counted as covered while contributing
    nothing renderable: the report prints exactly what each one filled.
    """
    names = sorted({r.get("scenario") for r in records if r.get("scenario")})
    rows = []
    for name in names:
        files = sorted({Path(r["_path"]).name for r in records if r.get("scenario") == name})
        counts = {label: counts_by_scenario.get(name, 0)
                  for label, counts_by_scenario in sections.items()
                  if counts_by_scenario.get(name)}
        rows.append({"scenario": name, "records": len(files), "sections": counts,
                     "rendered_rows": sum(counts.values()), "files": files})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(RUN_OUTPUT))
    parser.add_argument("--out-prefix", default="latency_profile")
    args = parser.parse_args()
    root = Path(args.root)
    records = load_records(root)
    if not records:
        raise SystemExit(f"no scenario records found under {root}")
    util_rows, comp_rows = flatten(records)
    switching = collect_switching(records)
    end_to_end, end_to_end_comps = collect_end_to_end(records)
    attribution = collect_attribution(records)
    memory = collect_memory(records)
    gates = collect_gates(records)
    RESULTS.mkdir(exist_ok=True)

    def by_scenario(rows):
        counts = {}
        for row in rows:
            counts[row["scenario"]] = counts.get(row["scenario"], 0) + 1
        return counts

    sections = {
        "utilization": by_scenario(util_rows),
        "comparisons": by_scenario(comp_rows),
        "end_to_end": by_scenario(end_to_end),
        "end_to_end_ratios": by_scenario(end_to_end_comps),
        "attribution": by_scenario(attribution),
        "memory": by_scenario(memory),
        "gates": by_scenario(gates),
        "switching": {name: len(entries) for name, entries in switching.items()},
    }
    coverage = scenario_coverage(records, sections)

    util_fields = ["scenario", "block", "key", "preset", "completed", "file",
                   "wall_ms_median", "wall_ms_p90", "wall_ms_cv",
                   "gpu_ms_median", "gpu_ms_p90", "gpu_ms_cv", "alpha_ms_median",
                   "tokens_per_step", "batch", "ctx_len", "prompt_len",
                   "flops", "bytes_moved_lower_bound", "achieved_bw_gbps", "bw_utilization",
                   "mfu", "kv_resident_bytes", "weight_bytes", "prefill_tok_s", "decode_tok_s",
                   "ffn_flop_share"]
    util_path = RESULTS / f"{args.out_prefix}.csv"
    with util_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=util_fields, extrasaction="ignore")
        writer.writeheader()
        for row in util_rows:
            writer.writerow(row)

    comp_fields = ["scenario", "grid", "metric", "large_key", "small_key", "n", "ratio",
                   "ci_lo", "ci_hi", "speedup", "mdd_ms", "mdd_pct", "median_delta_pct",
                   "ci_excludes_one", "appreciable", "verdict", "residual_bias_pct", "file"]
    comp_path = RESULTS / "comparisons.csv"
    with comp_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=comp_fields, extrasaction="ignore")
        writer.writeheader()
        for row in comp_rows:
            writer.writerow(row)

    # Detail CSVs: one per scenario whose payload the summary tables cannot hold, so
    # the data behind the report's new sections is plottable and diffable in-tree.
    def write_csv(path, rows, fields):
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return path

    e2e_path = write_csv(RESULTS / "s4_end_to_end.csv", end_to_end,
                         ["scenario", "key", "grid", "preset", "batch", "prompt_len",
                          "new_tokens", "generations", "ttft_ms_median", "ttft_ms_p90",
                          "itl_ms_median", "itl_ms_p90", "itl_ms_cv", "prefill_ms_median",
                          "e2e_ms_median", "decode_tok_s", "e2e_tok_s", "peak_alloc_gib",
                          "file", "completed"])
    e2e_comp_path = write_csv(RESULTS / "s4_end_to_end_ratios.csv", end_to_end_comps,
                              ["scenario", "grid", "preset", "metric", "n", "mean_ratio",
                               "ratio_lo", "ratio_hi", "speedup", "mdd_pct",
                               "median_delta_pct", "appreciable", "verdict", "interleaved",
                               "large_file", "small_file"])
    attrib_path = write_csv(RESULTS / "s6_attribution.csv", attribution,
                            ["scenario", "view", "regime", "preset", "step_gpu_ms",
                             "step_ms_median", "total_cuda_ms", "ffn_ms", "attributed_ms",
                             "ffn_share_attributed", "ffn_share_of_step",
                             "width_reduction_fraction", "in_scope_fraction",
                             "ceiling_speedup"]
                            + [f"share_{tag}" for tag in ATTRIBUTION_TAGS]
                            + ["file", "completed"])
    memory_path = write_csv(RESULTS / "s7_memory.csv", memory,
                            ["scenario", "preset", "measured_total_gib", "analytic_total_gib",
                             "analytic_minus_measured_pct", "peak_alloc_gib",
                             "kv_bytes_per_token", "max_batch_ctx_short", "max_batch_ctx_long",
                             "achieved_bw_gbps_prefill", "bw_utilization_prefill", "mfu_prefill",
                             "achieved_bw_gbps_decode", "bw_utilization_decode", "mfu_decode",
                             "ffn_flop_share_prefill", "ffn_flop_share_decode"]
                            + [f"weights_{bucket}_gib" for bucket in MEMORY_BUCKETS]
                            + ["file", "completed"])
    coverage_path = write_csv(RESULTS / "scenario_coverage.csv", coverage,
                              ["scenario", "records", "rendered_rows", "sections", "files"])

    # Group fits by decode (one query token) and prefill (many).
    # Identify the two regimes by the derived metrics each scenario publishes rather than by
    # a field only some of them set: an earlier version keyed prefill on ``prompt_len``,
    # which S2 never wrote, so the prefill fit silently had zero rows.
    decode_rows = [r for r in util_rows if r.get("decode_tok_s")]
    prefill_rows = [r for r in util_rows if r.get("prefill_tok_s")]
    fits = [fit_group(decode_rows, "decode_step"), fit_group(prefill_rows, "prefill")]

    appreciable = [r for r in comp_rows if r.get("appreciable")]
    with_ratio = [r for r in comp_rows if r.get("ratio")]
    best = min(with_ratio, key=lambda r: r["ratio"]) if with_ratio else None
    mdd_values = [r["mdd_pct"] for r in comp_rows if r.get("mdd_pct")]
    bias_values = [r["residual_bias_pct"] for r in comp_rows
                   if r.get("residual_bias_pct") is not None]
    summary = {
        "records": len(records),
        "switching_records": sum(len(v) for v in switching.values()),
        "switching_scenarios": sorted(switching),
        "scenarios": sorted({r.get("scenario") for r in records}),
        "utilization_rows": len(util_rows),
        "comparison_rows": len(comp_rows),
        "completed_records": sum(1 for r in records if r.get("completed")),
        "appreciable_effects": len(appreciable),
        "best_observed": best,
        "mdd_floor_pct": min(mdd_values) if mdd_values else None,
        "residual_bias_pct": max(bias_values) if bias_values else None,
        "end_to_end_rows": len(end_to_end),
        "end_to_end_comparisons": len(end_to_end_comps),
        "attribution_rows": len(attribution),
        "memory_rows": len(memory),
        "gate_passed": gates[0]["passed"] if gates else None,
        "gate_checks": gates[0]["checks"] if gates else [],
        "rendered_scenarios": [r["scenario"] for r in coverage if r["rendered_rows"]],
        "unrendered_scenarios": [r["scenario"] for r in coverage if not r["rendered_rows"]],
        "sections": sections,
        "coverage": coverage,
    }
    (RESULTS / f"{args.out_prefix}.json").write_text(json.dumps(
        {"summary": summary, "fits": fits, "utilization": util_rows,
         "comparisons": comp_rows, "end_to_end": end_to_end,
         "end_to_end_comparisons": end_to_end_comps, "attribution": attribution,
         "memory": memory, "gates": gates, "switching": switching}, indent=2) + "\n")
    (RESULTS / "crossover.json").write_text(json.dumps({"fits": fits}, indent=2) + "\n")
    (RESULTS / "switch_summary.json").write_text(json.dumps(switching, indent=2) + "\n")

    print(json.dumps(summary, indent=2, default=str))
    for fit in fits:
        print(json.dumps(fit if not fit.get("fitted") else
                         {k: v for k, v in fit.items() if k != "rows"}, indent=2, default=str))
    print(f"wrote {util_path}, {comp_path}, {e2e_path}, {e2e_comp_path}, {attrib_path}, "
          f"{memory_path}, {coverage_path}, {RESULTS / (args.out_prefix + '.json')}, "
          f"{RESULTS / 'crossover.json'}, {RESULTS / 'switch_summary.json'}")
    for entry in coverage:
        flag = "" if entry["rendered_rows"] else "  <-- present but not rendered"
        print(f"[coverage] {entry['scenario']}: {entry['rendered_rows']} rows "
              f"from {entry['records']} file(s){flag}")
    print("PASS analyze_latency", flush=True)


if __name__ == "__main__":
    main()

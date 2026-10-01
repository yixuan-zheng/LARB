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
    RESULTS.mkdir(exist_ok=True)

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
        "scenarios": sorted({r.get("scenario") for r in records}),
        "utilization_rows": len(util_rows),
        "comparison_rows": len(comp_rows),
        "completed_records": sum(1 for r in records if r.get("completed")),
        "appreciable_effects": len(appreciable),
        "best_observed": best,
        "mdd_floor_pct": min(mdd_values) if mdd_values else None,
        "residual_bias_pct": max(bias_values) if bias_values else None,
    }
    (RESULTS / f"{args.out_prefix}.json").write_text(json.dumps(
        {"summary": summary, "fits": fits, "utilization": util_rows,
         "comparisons": comp_rows}, indent=2) + "\n")
    (RESULTS / "crossover.json").write_text(json.dumps({"fits": fits}, indent=2) + "\n")

    print(json.dumps(summary, indent=2, default=str))
    for fit in fits:
        print(json.dumps(fit if not fit.get("fitted") else
                         {k: v for k, v in fit.items() if k != "rows"}, indent=2, default=str))
    print(f"wrote {util_path}, {comp_path}, {RESULTS / (args.out_prefix + '.json')}, "
          f"{RESULTS / 'crossover.json'}")
    print("PASS analyze_latency", flush=True)


if __name__ == "__main__":
    main()

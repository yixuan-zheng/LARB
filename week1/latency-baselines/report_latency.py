"""Render ``results/latency_profile.json`` into a compact markdown report.

The analyzer already emits machine-readable JSON and CSV. This is the human-readable
companion: a verdict summary first, then one section per scenario, with the pre-registered
verdicts and the uncertainty attached to every number. It renders every scenario that ran
-- including the ones whose payload does not fit the utilization/comparison tables -- and
names the raw file behind each block, so no decision-relevant number is reachable only by
digging through the git-ignored ``run-output/``. A scenario that produced nothing
renderable is reported as such rather than silently counted as covered.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
ALL_SCENARIOS = ("s0_harness_validation", "s1_decode_step", "s2_prefill", "s3_batch_decode",
                 "s4_end_to_end", "s5_backends", "s6_layer_profile", "s7_memory_roofline",
                 "s8_switch_mechanism", "s9_switch_phase", "s10_switch_iteration",
                 "s11_switch_flexibility")


def fmt(value, digits=2, suffix=""):
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value)
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join([" --- "] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join("-" if c is None else str(c) for c in row) + " |")
    return "\n".join(out)


def run_tag(row_or_file):
    """Short label for which run a row came from (``session``, ``smoke``, ``s3b``, ...)."""
    name = row_or_file if isinstance(row_or_file, str) else row_or_file.get("file", "")
    stem = name[:-5] if name.endswith(".json") else name
    parts = stem.split("__")
    return parts[-1] if len(parts) > 2 else "-"


def pct(value):
    return None if value is None else 100.0 * value


def source_note(rows_or_files):
    files = sorted({r["file"] if isinstance(r, dict) else r for r in rows_or_files})
    return "source: " + ", ".join(f"`{f}`" for f in files) if files else "no source files"


def ratio_span(comps):
    """Min/max paired mean ratio and the verdict mix across a set of comparisons."""
    ratios = [c.get("mean_ratio") or c.get("ratio") for c in comps]
    ratios = [r for r in ratios if r]
    if not ratios:
        return None, None, None
    verdicts = [c.get("verdict") for c in comps if c.get("verdict")]
    appreciable = sum(1 for v in verdicts if v == "appreciable")
    verdict = (f"appreciable in {appreciable}/{len(verdicts)}" if appreciable
               else ("within_noise" if verdicts else None))
    return min(ratios), max(ratios), verdict


def render_headline(lines, blob):
    """One compact table: the answer to each question the ladder was built to ask.

    Everything here is computed elsewhere in this report's inputs; the point is that
    no decisive result is reachable only by reading a table further down.
    """
    comps = blob.get("comparisons") or []
    e2e = blob.get("end_to_end_comparisons") or []
    attribution = blob.get("attribution") or []
    memory = blob.get("memory") or []
    gates = blob.get("gates") or []
    switching = blob.get("switching") or {}

    def span(scenarios):
        subset = [c for c in comps if c.get("scenario") in scenarios]
        gpu = [c for c in subset if c.get("metric") == "gpu_ms"]
        return ratio_span(gpu or subset)

    rows = []
    gate = gates[0] if gates else {}
    rows.append(["Instrument resolves a known effect (S0)",
                 f"{gate.get('n_checks', 0)} gating checks",
                 "pass" if gate.get("passed") else ("fail" if gates else "not run"),
                 "instrument gate"])
    lo, hi, verdict = span(("s1_decode_step",))
    rows.append(["Batch-1 decode speedup vs width",
                 f"ratio {fmt(lo, 4)}-{fmt(hi, 4)}" if lo else "-", verdict, "utilization"])
    lo, hi, verdict = span(("s3_batch_decode",))
    rows.append(["Batched decode speedup vs width",
                 f"ratio {fmt(lo, 4)}-{fmt(hi, 4)}" if lo else "-", verdict, "utilization"])
    lo, hi, verdict = span(("s2_prefill",))
    rows.append(["Prefill speedup vs width",
                 f"ratio {fmt(lo, 4)}-{fmt(hi, 4)}" if lo else "-", verdict, "utilization"])
    lo, hi, verdict = span(("s5_backends",))
    rows.append(["Backend choice vs width (eager/compile)",
                 f"ratio {fmt(lo, 4)}-{fmt(hi, 4)}" if lo else "-", verdict, "utilization"])
    lo, hi, verdict = ratio_span(e2e)
    rows.append(["End-to-end inter-token latency vs width (S4)",
                 f"ratio {fmt(lo, 4)}-{fmt(hi, 4)}" if lo else "-",
                 None if verdict is None else f"cross-process, {verdict}", "end-to-end"])
    module = [r for r in attribution if r.get("view") == "module"]
    ceilings = [r["ceiling_speedup"] for r in module if r.get("ceiling_speedup")]
    if ceilings:
        rows.append(["Ceiling if dispatch were free (S6)",
                     f"{fmt(min(ceilings), 3)}-{fmt(max(ceilings), 3)}x", "analytic bound",
                     "attribution"])
    large = next((r for r in memory if r.get("preset") == "large"), None)
    small = next((r for r in memory if r.get("preset") == "small"), None)
    if large and small and large.get("measured_total_gib") and small.get("measured_total_gib"):
        rows.append(["Resident weights Large minus Small (S7)",
                     f"{large['measured_total_gib'] - small['measured_total_gib']:.2f} GiB "
                     f"total, {large.get('weights_ffn_gib') - small.get('weights_ffn_gib'):.2f} "
                     f"GiB of it FFN", "exact", "memory"])
    dynamic = sorted(switching)
    rows.append(["Dynamic per-iteration switching (S8-S11)",
                 ", ".join(dynamic) if dynamic else "no switching records",
                 "measured" if dynamic else "not run",
                 "dynamic switching" if dynamic else "-"])

    lines += ["## Verdicts at a glance", "",
              "Each row is the short answer the rest of the report substantiates; `see` names",
              "the section that carries the evidence. Width ratios are the `gpu_ms` metric",
              "(the `wall_ms` rows in `results/comparisons.csv` track it to a few tenths of a",
              "percent).", "",
              table(["question", "measured", "verdict", "see"], rows), ""]
    return lines


def render_gate(lines, gates):
    if not gates:
        return lines
    rows = [[g["file"], g["passed"], g["n_checks"], ", ".join(g["checks"]), g["clock_ok"]]
            for g in gates]
    lines += ["## Instrument gate (s0)", "",
              "S0 proves the harness resolves a real effect and invents none; every other",
              "number is read in the units it establishes.", "",
              table(["file", "all checks passed", "# checks", "checks", "clock ok"], rows), ""]
    return lines


def render_coverage(lines, summary):
    """Per-scenario accounting: a scenario that ran but filled no table is named."""
    coverage = summary.get("coverage") or []
    if not coverage:
        return lines
    body = []
    for entry in coverage:
        sections = ", ".join(f"{name} {count}"
                             for name, count in sorted(entry["sections"].items()))
        body.append([entry["scenario"], entry["records"], entry["rendered_rows"] or "**none**",
                     sections or "**nothing rendered**"])
    unrendered = summary.get("unrendered_scenarios") or []
    lines += ["## Coverage", "",
              "One row per scenario that ran, with the number of rows it contributed to each",
              "table. A scenario showing `none` is present in the record set but produced",
              "nothing renderable -- a reporting gap, not evidence of absence.", "",
              table(["scenario", "records", "rendered rows", "tables filled"], body), "",
              table(["field", "value"], [
                  ["records", summary.get("records")],
                  ["completed records", summary.get("completed_records")],
                  ["utilization rows", summary.get("utilization_rows")],
                  ["comparison rows", summary.get("comparison_rows")],
                  ["end-to-end rows", summary.get("end_to_end_rows")],
                  ["s6 attribution rows", summary.get("attribution_rows")],
                  ["s7 memory rows", summary.get("memory_rows")],
                  ["appreciable effects", summary.get("appreciable_effects")],
                  ["MDD floor", fmt(summary.get("mdd_floor_pct"), 2, "%")],
                  ["residual harness bias", fmt(summary.get("residual_bias_pct"), 2, "%")],
              ]), ""]
    if unrendered:
        lines += ["Scenarios present but not rendered: "
                  + ", ".join(f"`{s}`" for s in unrendered) + ".", ""]
    return lines


def render_end_to_end(lines, rows, comps):
    if not rows:
        return lines
    body = [[r["preset"], r["grid"], r["batch"], r["prompt_len"], r["new_tokens"],
             fmt(r["ttft_ms_median"], 1), fmt(r["ttft_ms_p90"], 1),
             fmt(r["itl_ms_median"], 2), fmt(r["itl_ms_p90"], 2),
             fmt(r["e2e_ms_median"], 0), fmt(r["decode_tok_s"], 1), fmt(r["e2e_tok_s"], 1)]
            for r in sorted(rows, key=lambda x: (x["grid"], x["preset"]))]
    lines += ["## End-to-end generation (s4)", "",
              "TTFT, inter-token latency, whole-request time and throughput -- the numbers a",
              "reader would actually quote. Per-config rows: `results/s4_end_to_end.csv`.", "",
              table(["preset", "grid", "batch", "prompt", "new tok", "TTFT p50 ms",
                     "TTFT p90 ms", "ITL p50 ms", "ITL p90 ms", "e2e p50 ms", "decode tok/s",
                     "e2e tok/s"], body), "",
              f"_{source_note(rows)}_", ""]
    if comps:
        body = [[c["grid"], c["preset"], c["n"], fmt(c["mean_ratio"], 4),
                 f"[{fmt(c['ratio_lo'], 4)}, {fmt(c['ratio_hi'], 4)}]",
                 fmt(c["mdd_pct"], 2, "%"), fmt(c["median_delta_pct"], 2, "%"), c["verdict"]]
                for c in sorted(comps, key=lambda x: (x["grid"], x["preset"]))]
        lines += ["### Width ratio from the per-step samples (cross-process)", "",
                  "S4 runs one preset per process, so this ratio joins the same grid across the",
                  "three files instead of using the interleaved in-process pairing the other",
                  "scenarios use. The bootstrap still pairs step indices, but the samples were",
                  "not collected interleaved: read it as corroboration, not as a pre-registered",
                  "verdict. Rows: `results/s4_end_to_end_ratios.csv`.", "",
                  table(["grid", "vs large", "n", "ratio", "ratio 95% CI", "MDD",
                         "median delta", "verdict"], body), ""]
    return lines


def render_attribution(lines, rows):
    if not rows:
        return lines
    module = [r for r in rows if r["view"] == "module"]
    if module:
        body = []
        for r in sorted(module, key=lambda x: (x["regime"], x["preset"])):
            body.append([r["regime"], r["preset"], fmt(r["step_gpu_ms"], 1),
                         fmt(r["ffn_ms"], 1), fmt(pct(r["ffn_share_of_step"]), 1),
                         fmt(pct(r["ffn_share_attributed"]), 1),
                         fmt(pct(r["width_reduction_fraction"]), 1),
                         fmt(pct(r["in_scope_fraction"]), 1), fmt(r["ceiling_speedup"], 3)])
        lines += ["## Where the step time goes, and the ceiling (s6)", "",
                  "`FFN % step` divides by the timed step (which the event hooks inflate);",
                  "`FFN % attributed` divides by the summed timed modules (now including AltUp).",
                  "`in scope` is the attributed FFN share times the ~28.6% of FFN weights a slice",
                  "removes, and `ceiling` is the speedup if that in-scope portion became free. It",
                  "is a bound at *this* grid -- S6's own large-vs-small prefill step ratio sits",
                  "inside the large preset's ceiling. Grids with a lighter attention load carry a",
                  "larger FFN share (hence a higher ceiling), so a ratio measured elsewhere",
                  "(S2/S5) can sit slightly above this grid's bound.", "",
                  table(["regime", "preset", "step ms", "FFN ms", "FFN % step",
                         "FFN % attributed", "width cut %", "in scope %", "ceiling x"], body), ""]
        for regime in ("decode", "prefill"):
            subset = [r for r in module if r["regime"] == regime]
            tags = sorted({k[len("share_"):] for r in subset for k in r if k.startswith("share_")})
            if not subset or not tags:
                continue
            body = [[r["preset"]] + [fmt(pct(r.get(f"share_{t}")), 1) for t in tags]
                    for r in sorted(subset, key=lambda x: x["preset"])]
            lines += [f"Per-module {regime} time share:", "",
                      table(["preset"] + [f"{t} %" for t in tags], body), ""]
    kernel = [r for r in rows if r["view"] == "kernel"]
    if kernel:
        tags = sorted({k[len("share_"):] for r in kernel for k in r if k.startswith("share_")})
        body = [[r["regime"], r["preset"], fmt(r["total_cuda_ms"], 1)] +
                [fmt(pct(r.get(f"share_{t}")), 1) for t in tags]
                for r in sorted(kernel, key=lambda x: (x["regime"], x["preset"]))]
        lines += ["### Kernel-category view (independent of the module view)", "",
                  "From a `torch.profiler` CUDA-activity pass. The matmul share is a second,",
                  "independent estimate of what a width change can touch; a module-level FFN",
                  "share that disagrees with the matmul share is itself a finding.", "",
                  table(["regime", "preset", "cuda ms"] + [f"{t} %" for t in tags], body), "",
                  f"_{source_note(rows)}_", ""]
    return lines


def render_memory(lines, rows):
    if not rows:
        return lines
    body = [[r["preset"], fmt(r["measured_total_gib"], 2), fmt(r["analytic_total_gib"], 2),
             fmt(r["analytic_minus_measured_pct"], 2, "%"), fmt(r["weights_ffn_gib"], 2),
             fmt(r["weights_embeddings_gib"], 2),
             fmt(r["kv_bytes_per_token"] / 1024.0 if r["kv_bytes_per_token"] else None, 1),
             r["max_batch_ctx_short"], r["max_batch_ctx_long"], fmt(r["peak_alloc_gib"], 2)]
            for r in rows]
    lines += ["## Memory, capacity and roofline (s7)", "",
              "The memory story is arithmetically certain even where the latency story is flat:",
              "narrowing the FFN removes its weight bytes from every resident copy, and the",
              "freed capacity buys batch, context or a second model. `analytic - measured` is",
              "the model-versus-reality check; a large value would invalidate the cost model.",
              "KV per token is measured off the live cache, not assumed.", "",
              table(["preset", "weights GiB", "analytic GiB", "analytic - measured", "FFN GiB",
                     "embeddings GiB", "KV KiB/token", "max batch ctx 1", "max batch ctx long",
                     "peak VRAM GiB"], body), ""]
    body = [[r["preset"], fmt(r["achieved_bw_gbps_prefill"], 1),
             fmt(pct(r["bw_utilization_prefill"]), 1), fmt(pct(r["mfu_prefill"]), 2),
             fmt(pct(r["ffn_flop_share_prefill"]), 1),
             fmt(r["achieved_bw_gbps_decode"], 1), fmt(pct(r["bw_utilization_decode"]), 1),
             fmt(pct(r["mfu_decode"]), 2), fmt(pct(r["ffn_flop_share_decode"]), 1)]
            for r in rows]
    lines += ["Roofline utilization at the measured point (`results/s7_memory.csv` carries the",
              "full row set, including every weight bucket):", "",
              table(["preset", "prefill GB/s", "prefill % peak BW", "prefill MFU %",
                     "prefill FFN FLOP %", "decode GB/s", "decode % peak BW", "decode MFU %",
                     "decode FFN FLOP %"], body), "",
              f"_{source_note(rows)}_", ""]
    return lines


def render_provenance(lines, summary):
    coverage = summary.get("coverage") or []
    if not coverage:
        return lines
    body = [[e["scenario"], e["records"],
             "<br>".join(f"`{f}`" for f in e["files"]) or "-"] for e in coverage]
    lines += ["## Provenance", "",
              "Every table above is derived from these scenario records. The raw records live",
              "in the git-ignored `run-output/`; the extracted, reviewable copies are the",
              "tracked `results/*.json` and `results/*.csv` files written by",
              "`analyze_latency.py`.", "",
              table(["scenario", "records", "files"], body), ""]
    return lines


def render_switching(lines, switching):
    """Render the dynamic-switching (s8-s11) blocks the scenarios emit."""
    if not switching:
        return lines
    lines += ["## Dynamic switching (s8-s11)", "",
              "Rendered from the `switching` block each dynamic scenario emits. `tax` is",
              "dynamic-at-W minus static-at-W as a percentage of static: positive means the",
              "switchable path is slower than a physically static model at the same width.", ""]

    for entry in switching.get("s8_switch_mechanism", []):
        sw = entry["switching"]
        eq = (sw.get("equivalence") or {}).get("per_width", {})
        if eq:
            rows = [[p, fmt(v.get("max_abs_logit"), 4), v.get("same_argmax"), v.get("passed"),
                     v.get("reference")] for p, v in sorted(eq.items())]
            lines += ["### S8 equivalence gate", "",
                      table(["width", "max dlogit", "argmax agrees", "passed", "reference"], rows), ""]
        eqd = (sw.get("equivalence_decode") or {}).get("per_width", {})
        if eqd:
            rows = [[p, fmt(v.get("max_abs_logit"), 4), v.get("same_argmax"), v.get("passed"),
                     v.get("reference")] for p, v in sorted(eqd.items())]
            lines += ["### S8 decode-path equivalence (KV cache present)", "",
                      table(["width", "max dlogit", "argmax agrees", "passed", "reference"], rows), ""]
        ops = sw.get("switch_op_us", {})
        if ops:
            rows = [[k, fmt(v.get("median"), 2), fmt(v.get("p90"), 2)] for k, v in sorted(ops.items())]
            lines += ["### S8 switch-operation cost (host)", "",
                      table(["plan", "median us", "p90 us"], rows), ""]
        rows = []
        for workload, modes in sorted((sw.get("tax") or {}).items()):
            for mode, comps in sorted(modes.items()):
                for name, v in sorted(comps.items()):
                    rows.append([workload, mode, name, fmt(v.get("tax_pct"), 2, "%"), v.get("verdict")])
        if rows:
            lines += ["### S8 mechanism tax", "",
                      table(["workload", "slice_mode", "comparison", "tax", "verdict"], rows), ""]
        cold = sw.get("cold_switch", {})
        if cold:
            rows = [[w, fmt(v.get("cold_minus_warm_pct"), 2, "%"), v.get("verdict")]
                    for w, v in sorted(cold.items())]
            lines += ["### S8 cold-switch penalty (prefill)", "",
                      table(["width", "cold - warm", "verdict"], rows), ""]
        null = sw.get("null", {})
        if null:
            rows = [[w, fmt(v.get("mean_ratio"), 4), v.get("verdict"), v.get("passed")]
                    for w, v in sorted(null.items())]
            lines += ["### S8 null control", "",
                      table(["workload", "ratio", "verdict", "passed"], rows), ""]

    for entry in switching.get("s9_switch_phase", []):
        rows = []
        for grid, v in sorted((entry["switching"].get("grids") or {}).items()):
            if "prefill_capture_fraction" not in v and "prefill_capture_fraction_raw" not in v:
                continue
            bnd = v.get("boundary_switch_cost_ms") or {}
            resolvable = v.get("capture_resolvable")
            if resolvable:
                cap_str = fmt(v.get("prefill_capture_fraction"), 3)
            else:
                raw = v.get("prefill_capture_fraction_raw")
                cap_str = "-" if raw is None else f"n/a (raw {raw:.2f})"
            rows.append([grid, fmt(v.get("prefill_delta_ms"), 2),
                         fmt(v.get("prefill_delta_pct"), 1, "%"), cap_str,
                         "yes" if resolvable else ("no" if resolvable is False else "-"),
                         fmt(bnd.get("small_to_large"), 2), fmt(bnd.get("large_to_small"), 2)])
        if rows:
            lines += ["### S9 prefill/decode boundary", "",
                      "The capture fraction divides the phase schedule's prefill saving by the",
                      "static large-minus-small prefill difference. Where that difference is not",
                      "resolvable (low arithmetic intensity) the ratio is noise and is shown as",
                      "`n/a` with its raw value.", "",
                      table(["grid", "prefill delta ms", "delta %", "prefill capture",
                             "resolvable", "boundary s->l ms", "boundary l->s ms"], rows), ""]

    for entry in switching.get("s10_switch_iteration", []):
        rows, sched_rows = [], []
        for grid, v in sorted((entry["switching"].get("grids") or {}).items()):
            conds = v.get("conditions") or {}
            alt = conds.get("alt_large_small", {})
            cl = (conds.get("const_large") or {}).get("step_wall_ms") or {}
            cs = (conds.get("const_small") or {}).get("step_wall_ms") or {}
            resolvable = v.get("width_effect_resolvable")
            rows.append([grid, fmt(v.get("const_width_delta_ms"), 3),
                         "yes" if resolvable else ("no" if resolvable is False else "-"),
                         fmt(alt.get("alternation_overhead_pct"), 2, "%"),
                         fmt(cl.get("median"), 3), fmt(cs.get("median"), 3)])
            for name, cond in sorted(conds.items()):
                if name in ("const_large", "const_small", "static_small"):
                    continue
                if cond.get("alternation_overhead_pct") is None:
                    continue
                sched_rows.append([grid, name, fmt(cond.get("alternation_overhead_pct"), 2, "%"),
                                   cond.get("n_switches")])
        if rows:
            lines += ["### S10 iteration-level switching", "",
                      "`width delta` is the static large-minus-small step difference. Where it",
                      "is not resolvable the alternation overhead is within noise by",
                      "construction and must not be read as \"switching is free\".", "",
                      table(["grid", "width delta ms", "width resolvable", "alternation overhead",
                             "const large ms", "const small ms"], rows), "",
                      "Every switching schedule in the record (the table above shows only",
                      "`alternate`); the worst row bounds the per-schedule switching cost:", "",
                      table(["grid", "schedule", "alternation overhead", "switches"], sched_rows), ""]

    for entry in switching.get("s11_switch_flexibility", []):
        sw = entry["switching"]
        wg = sw.get("weights_gib", {})
        if wg:
            rows = [[k, fmt(v, 2)] for k, v in sorted(wg.items())]
            lines += ["### S11 weights per option (GiB)", "", table(["option", "GiB"], rows), ""]
        cap = sw.get("capacity", {})
        if cap:
            rows = [[k, v.get("max_batch")] for k, v in sorted(cap.items())]
            lines += ["### S11 max batch before OOM", "", table(["model/context", "max batch"], rows), ""]
            cap_cap = sw.get("capacity_cap")
            by_ctx = {}
            for k, v in cap.items():
                by_ctx.setdefault(k.rsplit("_L", 1)[-1], []).append(v.get("max_batch"))
            if by_ctx and all(len(set(vals)) == 1 for vals in by_ctx.values()):
                parts = ", ".join(f"ctx {c}: {vals[0]}" for c, vals in sorted(by_ctx.items()))
                lines += ["_Every option reached the same max batch per context (" + parts + ").",
                          "The probe runs with one model resident at a time, so this is not a",
                          "co-residency artefact: in these regimes the ~1.9 GiB FFN-width",
                          "difference does not move the batch cap (the short-context row is",
                          f"`--capacity-cap`-limited ({cap_cap}); at long context activations and",
                          "KV dominate the weight delta)._", ""]
        rt = sw.get("retarget", {})
        if rt.get("apply_us"):
            lines += ["Retarget cost (host apply): median "
                      f"{fmt(rt['apply_us'].get('median'), 2)} us vs a reload of "
                      f"{fmt((rt.get('load_seconds') or {}).get('large'), 1)} s.", ""]

    lines += ["_A dynamic scenario missing here did not run or did not complete; that is not",
              "evidence of absence._", ""]
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in", dest="src", default=str(RESULTS / "latency_profile.json"))
    parser.add_argument("--out", dest="dst", default=str(RESULTS / "latency_report.md"))
    args = parser.parse_args()
    blob = json.loads(Path(args.src).read_text())
    summary, fits = blob.get("summary", {}), blob.get("fits", [])
    util, comps = blob.get("utilization", []), blob.get("comparisons", [])
    end_to_end = blob.get("end_to_end", [])
    end_to_end_comps = blob.get("end_to_end_comparisons", [])
    attribution = blob.get("attribution", [])
    memory = blob.get("memory", [])
    gates = blob.get("gates", [])

    lines = ["# FFN width latency profile", "",
             "Generated from `results/latency_profile.json` by `report_latency.py`. Every ratio",
             "in the paired tables is a *paired* mean ratio over shuffled, interleaved samples;",
             "`verdict` follows the pre-registered rule (bootstrap CI excludes 1.0 **and**",
             "|median delta| > 2%). Sections are ordered so the answer comes before its",
             "evidence; `Provenance` maps every block back to the record it came from.", ""]

    lines = render_headline(lines, blob)
    lines = render_gate(lines, gates)
    lines = render_coverage(lines, summary)

    if util:
        rows = []
        for r in sorted(util, key=lambda x: (x.get("scenario", ""), x.get("key", ""))):
            rows.append([r.get("scenario"), r.get("key"), run_tag(r), r.get("preset"),
                         fmt(r.get("gpu_ms_median"), 3), fmt(r.get("alpha_ms_median") or
                                                              r.get("alpha_ms"), 3),
                         fmt(r.get("achieved_bw_gbps"), 1),
                         fmt(100 * r["bw_utilization"] if r.get("bw_utilization") else None, 1),
                         fmt(100 * r["mfu"] if r.get("mfu") else None, 3),
                         fmt(r.get("decode_tok_s") or r.get("prefill_tok_s"), 1)])
        lines += ["## Utilization per configuration", "",
                  "`run` distinguishes rows that share a config but came from different files",
                  "(for example the `session` and `smoke` S1 runs). Full table:",
                  "`results/latency_profile.csv`.", "",
                  table(["scenario", "config", "run", "preset", "gpu ms", "alpha ms", "BW GB/s",
                         "BW % peak", "MFU %", "tok/s"], rows), ""]

    if comps:
        rows = []
        for r in sorted(comps, key=lambda x: (x.get("scenario", ""), x.get("grid", ""),
                                              x.get("metric") or "")):
            rows.append([r.get("scenario"), r.get("grid"), r.get("metric"), run_tag(r),
                         fmt(r.get("speedup"), 4), f"[{fmt(r.get('ci_lo'), 4)}, {fmt(r.get('ci_hi'), 4)}]",
                         fmt(r.get("mdd_pct"), 2, "%"), fmt(r.get("median_delta_pct"), 2, "%"),
                         r.get("verdict")])
        lines += ["## Large vs Small (paired)", "",
                  "In-process, interleaved, so the pairing cancels slow clock/thermal drift.",
                  "`run` distinguishes rows that share a grid and metric but came from different",
                  "files. Full table: `results/comparisons.csv`.", "",
                  table(["scenario", "grid", "metric", "run", "speedup", "ratio 95% CI", "MDD",
                         "median delta", "verdict"], rows), ""]

    lines = render_end_to_end(lines, end_to_end, end_to_end_comps)
    lines = render_attribution(lines, attribution)
    lines = render_memory(lines, memory)

    if fits:
        rows = []
        for f in fits:
            coef = f.get("coef") or {}
            rows.append([f.get("label"), f.get("fitted"), f.get("n_rows"),
                         fmt(coef.get("intercept_ms"), 3),
                         fmt(coef.get("ms_per_token"), 4),
                         fmt(coef.get("ms_per_weight_byte") * 1e9 if coef.get("ms_per_weight_byte") else None, 4),
                         fmt(f.get("r2"), 4), f.get("reason") or ""])
        lines += ["## Fitted cost model", "",
                  table(["group", "fitted", "rows", "intercept ms", "ms/token",
                         "ms per GB weights", "R2", "note"], rows),
                  "",
                  "`ms per GB weights` is the fitted marginal cost of one GiB of resident FFN",
                  "width in that regime; multiplying it by the Large-minus-Small weight",
                  "difference gives the predicted width effect, which the measured ratio is",
                  "then compared against. Across the three presets, FFN weight bytes and FFN",
                  "FLOPs scale identically with the summed layer width, so a single coefficient",
                  "cannot separate the two. The mechanism is pinned down separately: the",
                  "per-token saving divided into the removed FLOPs implies ~161 TFLOPS, i.e.",
                  "44% of bf16 dense peak, which is a compute-bound rate and not a",
                  "bandwidth-bound one.", ""]
        for f in fits:
            we = f.get("width_effect")
            r2 = f.get("r2")
            if f.get("fitted") and r2 is not None and r2 < 0.5:
                lines += [f"*{f['label']}: R2={fmt(r2, 3)}. This fit is **not identified** -- its",
                          "weight coefficient is estimated from only a few distinct weight values",
                          "under a dominant nuisance trend -- so the width effect below is reported",
                          "for completeness and is not evidence of a mechanism. Use the paired",
                          "Large-vs-Small table for that regime.*", ""]
            if we:
                tail = ""
                if we.get("predicted_speedup_at_batch1"):
                    tail = (f" (speedup "
                            f"{fmt(we['predicted_speedup_at_batch1'], 4)} at batch 1)")
                lines += [f"**{f['label']}** predicted width effect: "
                          f"{we['delta_bytes'] / 1024**3:.2f} GiB less -> "
                          f"{we['predicted_delta_ms']:.3f} ms less per step{tail}.", ""]
            if f.get("dropped_collinear"):
                names = ", ".join(f"{d['name']} (constant {d['constant']})"
                                  for d in f["dropped_collinear"])
                lines += [f"*{f['label']}: dropped collinear regressors: {names}.*", ""]

    lines = render_switching(lines, blob.get("switching") or {})
    lines = render_provenance(lines, summary)

    missing = [s for s in ALL_SCENARIOS if s not in (summary.get("scenarios") or [])]
    if missing:
        lines += ["## Not measured in this run", "",
                  ", ".join(f"`{m}`" for m in missing), "",
                  "A missing scenario means it did not run or did not complete; it is not",
                  "evidence of absence.", ""]
    unrendered = summary.get("unrendered_scenarios") or []
    if unrendered:
        lines += ["## Present but not rendered", "",
                  ", ".join(f"`{s}`" for s in unrendered), "",
                  "These scenarios ran (their records are in the profile) but contributed no",
                  "row to any table: their payload does not match an extractor. This is a",
                  "reporting gap, not a measurement result -- fix the extractor or the",
                  "scenario's record shape before quoting any summary that counts them.", ""]

    Path(args.dst).write_text("\n".join(lines) + "\n")
    print(f"wrote {args.dst} ({len(lines)} lines)")
    print("PASS report_latency", flush=True)


if __name__ == "__main__":
    main()

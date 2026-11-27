"""P3C prefilled-cohort cut-stress experiment.

Tests the most favorable natural case for an in-flight cut: a 64-request
burst arrives while 32 requests already occupy all slots at 8k.  Admission can
only change new arrivals; a cut can free the running cohort earlier.

Arms: fixed4k, fixed6k, fixed8k, arrival, live4k, live6k.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from pathlib import Path

from larb_week8 import config, pilot, runner

CONFIG_PATH = pilot.PREFILL_CONFIG_PATH
TRACE_DIR = pilot.TRACE_DIR


def load_config() -> dict:
    return config.read_json(CONFIG_PATH)


def build_all(trace_dir: Path | None = None) -> dict:
    return pilot.build_prefill_all(trace_dir)


def plan(cfg: dict | None = None, trace_dir: Path | None = None) -> list[dict]:
    return pilot.plan_prefill(cfg, trace_dir)


def run(out: Path, trace_dir: Path | None = None) -> None:
    if not os.environ.get("SLURM_JOB_ID") and os.environ.get("LARB_ALLOW_NO_SLURM") != "1":
        raise RuntimeError("GPU execution requires a Slurm allocation (or LARB_ALLOW_NO_SLURM=1)")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    phases = plan(cfg, trace_dir)
    config.write_json(out / "prefill-manifest.json", {
        "config": str(CONFIG_PATH.relative_to(config.WEEK8_ROOT)),
        "config_sha256": config.digest(CONFIG_PATH),
        "job": os.environ.get("SLURM_JOB_ID"),
        "started": config.utc_now(),
        "trace": config.digest(Path(trace_dir or TRACE_DIR) /
                               f"{cfg['design']['trace_name']}.jsonl"),
        "phases": [phase["name"] for phase in phases],
        "code_hashes": config.code_hashes(),
        "week7_source_lock": config.verify_week7_source_lock(),
    })
    runner.run_sequence(phases, out)


def _subset(rows: list[dict], name: str) -> list[dict]:
    return [row for row in rows if row.get(name)]


def _phase_metrics(run_dir: Path, phases: list[dict], cfg: dict) -> list[dict]:
    metrics = pilot._phase_metrics(Path(run_dir), phases, cfg)
    by_name = {phase["name"]: phase for phase in phases}
    for item in metrics:
        phase = by_name.get(item["phase"], {})
        item["policy_label"] = phase.get("policy_label", item.get("arm"))
    return metrics


def decide(result: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    rules = cfg["decision"]
    by_arm = result["by_arm"]
    paired = result["paired"]
    phases = result["phases"]
    expected_labels = [item["label"] for item in cfg["design"]["arms"]]
    seen_labels = {phase.get("policy_label", phase["arm"]) for phase in phases}
    coverage_ok = (seen_labels == set(expected_labels) and
                   all(phase.get("injection_valid", True) for phase in phases))
    metrics = result["phase_metrics"]
    by_label = {item["policy_label"]: item for item in metrics}
    live_labels = [label for label in expected_labels if label.startswith("live")]
    fixed_labels = [label for label in expected_labels if label.startswith("fixed")]
    live_cuts = {label: by_label.get(label, {}).get("cuts", 0) for label in live_labels}
    live_each_cut = all(live_cuts.get(label, 0) > 0 for label in live_labels)
    cut_after_close = sum(by_label.get(label, {}).get("cut_after_close", 0)
                          for label in live_labels)
    live_short = {label: by_label.get(label, {}).get("admission_budget_short", 0)
                  for label in live_labels}
    live_long = {label: by_label.get(label, {}).get("admission_budget_long", 0)
                 for label in live_labels}
    fixed_cuts = sum(by_label.get(label, {}).get("cuts", 0) for label in fixed_labels)
    validity = {
        "coverage_ok": bool(coverage_ok),
        "live_cuts": live_cuts,
        "live_each_phase_has_cut": bool(live_each_cut),
        "cut_after_close": cut_after_close,
        "live_admission_short": live_short,
        "live_admission_long": live_long,
        "fixed_arm_cuts": fixed_cuts,
        "request_errors": sum(phase.get("errors", 0) for phase in phases),
        "request_missing": sum(item.get("missing", 0) for item in by_arm.values()),
        "pass": bool(coverage_ok and live_each_cut and cut_after_close == 0
                     and all(live_short.get(label, 0) > 0 for label in live_labels)
                     and all(live_long.get(label, 0) > 0 for label in live_labels)
                     and fixed_cuts == 0),
    }
    if not live_labels:
        return {
            "decision": "admission_only" if validity["pass"] else "invalid",
            "reasons": ([f"admission-only replication: {len(expected_labels)} arms, no live cut"]
                        if validity["pass"] else ["admission-only validity failed"]),
            "validity": validity,
            "best_live_label": None,
            "best_live_minus_arrival_correct_on_time": None,
            "best_live_minus_arrival_accuracy": None,
            "best_live_minus_fixed8k_accuracy": None,
            "live_vs_arrival_correct_on_time": {},
            "thresholds": rules,
        }

    def diff(name, field):
        return (paired.get(name, {}).get(field, {}) or {}).get("mean_diff")

    arrival_vs = {label: diff(f"{label}_vs_arrival", "correct_on_time")
                  for label in live_labels}
    best_label = max(live_labels, key=lambda label: arrival_vs.get(label) or -1.0)
    best_good = arrival_vs.get(best_label)
    best_acc = diff(f"{best_label}_vs_arrival", "correct") if best_label else None
    best_vs_8k = diff(f"{best_label}_vs_fixed8k", "correct") if best_label else None
    both_accuracy_bad = all((diff(f"{label}_vs_arrival", "correct") or 0) < -0.10
                            for label in live_labels)
    reasons = []
    if not validity["pass"]:
        reasons.append("prefill manipulation/coverage validity failed")
        decision = "invalid"
    elif best_good is None or best_good <= 0:
        reasons.append("no live variant beats arrival on correct-on-time")
        decision = "stop_cut"
    elif both_accuracy_bad:
        reasons.append("both live variants are more than 10 points below arrival on accuracy")
        decision = "stop_quality"
    else:
        go = rules["cut_go_if"]
        if (best_good >= go["best_live_minus_arrival_correct_on_time_min"]
                and best_acc is not None and best_acc >= go["best_live_minus_arrival_accuracy_min"]
                and best_vs_8k is not None and best_vs_8k >= go["best_live_minus_fixed8k_accuracy_min"]):
            reasons.append(f"{best_label} beats arrival on correct-on-time and keeps accuracy "
                           "within the pre-declared bounds")
            decision = "go_cut"
        else:
            reasons.append("best live variant is between the stop and GO thresholds")
            decision = "inconclusive"
    return {
        "decision": decision,
        "reasons": reasons,
        "validity": validity,
        "best_live_label": best_label,
        "best_live_minus_arrival_correct_on_time": best_good,
        "best_live_minus_arrival_accuracy": best_acc,
        "best_live_minus_fixed8k_accuracy": best_vs_8k,
        "live_vs_arrival_correct_on_time": arrival_vs,
        "thresholds": rules,
    }


def analyse(run_dir: Path, out_dir: Path | None = None,
            cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    run_dir = Path(run_dir)
    out_dir = Path(out_dir or run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, phases = pilot.build_rows(run_dir)
    labels = [item["label"] for item in cfg["design"]["arms"]]
    by_arm = {label: pilot.summarize([row for row in rows if row["arm"] == label])
              for label in labels}
    by_burst = {label: pilot.summarize([row for row in rows
                                        if row["arm"] == label and row["burst"]])
                for label in labels}
    by_cohort = {label: pilot.summarize([row for row in rows
                                         if row["arm"] == label and row["cohort"]])
                 for label in labels}
    by_tail = {label: pilot.summarize([row for row in rows
                                       if row["arm"] == label and row["tail"]])
               for label in labels}
    phase_metrics = _phase_metrics(run_dir, phases, cfg)
    metrics_by_label = {item["policy_label"]: item for item in phase_metrics}
    for label, item in by_arm.items():
        item["worker_cuts"] = metrics_by_label.get(label, {}).get("cuts", 0)
        item["worker_cut_requests"] = metrics_by_label.get(label, {}).get("cut_requests", 0)
    comparisons = (
        ("fixed4k", "fixed6k"), ("fixed4k", "fixed8k"), ("fixed6k", "fixed8k"),
        ("arrival", "fixed4k"), ("arrival", "fixed6k"), ("arrival", "fixed8k"),
        ("live4k", "arrival"), ("live6k", "arrival"),
        ("live4k", "fixed4k"), ("live6k", "fixed4k"),
        ("live4k", "fixed8k"), ("live6k", "fixed6k"), ("live6k", "fixed8k"),
        ("live4k", "live6k"),
    )
    paired = {}
    for arm_a, arm_b in comparisons:
        name = f"{arm_a}_vs_{arm_b}"
        paired[name] = {
            "correct": pilot.paired_question(rows, arm_a, arm_b, "correct"),
            "correct_on_time": pilot.paired_question(rows, arm_a, arm_b, "good"),
            "response_correct": pilot.paired_response(rows, arm_a, arm_b, "correct"),
            "response_correct_on_time": pilot.paired_response(rows, arm_a, arm_b, "good"),
        }
    result = {
        "generated_at": config.utc_now(),
        "run_dir": str(run_dir),
        "design": cfg["design"],
        "phases": phases,
        "phase_metrics": phase_metrics,
        "by_arm": by_arm, "by_burst": by_burst,
        "by_cohort": by_cohort, "by_tail": by_tail,
        "paired": paired,
        "rows": rows,
        "caveats": [
            "Screening extension, not a powered P3; the planned MDE is roughly 12-16 points.",
            "Caps, missing outputs, late answers and errors stay in the denominator.",
            "Cut counts use worker.jsonl; request-record cut lists can miss a cut.",
            "The prefilled cohort is the most favorable natural case for a cut, not a representative load.",
        ],
    }
    result["decision"] = decide(result, cfg)
    config.write_json(out_dir / "prefill.json", result)
    config.write_json(out_dir / "summary.json", {
        "by_arm": by_arm, "by_burst": by_burst, "by_cohort": by_cohort,
        "by_tail": by_tail, "phase_metrics": phase_metrics,
        "decision": result["decision"],
    })
    with (out_dir / "paired.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["comparison", "field", "n", "mean_diff", "ci_low", "ci_high",
                         "wins", "losses", "ties"])
        for name, block in paired.items():
            for field in ("correct", "correct_on_time"):
                item = block[field]
                if not item.get("n"):
                    continue
                writer.writerow([name, field, item["n"], item["mean_diff"],
                                 item["ci_low"], item["ci_high"],
                                 item["wins"], item["losses"], item["ties"]])
    write_markdown(result, out_dir / "PREFILL.md")
    return result


def _paired_block(rows: list[dict]) -> dict:
    comparisons = (
        ("fixed4k", "fixed6k"), ("fixed4k", "fixed8k"), ("fixed6k", "fixed8k"),
        ("arrival", "fixed4k"), ("arrival", "fixed6k"), ("arrival", "fixed8k"),
        ("live4k", "arrival"), ("live6k", "arrival"),
        ("live4k", "fixed4k"), ("live6k", "fixed4k"),
        ("live4k", "fixed8k"), ("live6k", "fixed6k"), ("live6k", "fixed8k"),
        ("live4k", "live6k"),
    )
    paired = {}
    for arm_a, arm_b in comparisons:
        name = f"{arm_a}_vs_{arm_b}"
        paired[name] = {
            "correct": pilot.paired_question(rows, arm_a, arm_b, "correct"),
            "correct_on_time": pilot.paired_question(rows, arm_a, arm_b, "good"),
            "response_correct": pilot.paired_response(rows, arm_a, arm_b, "correct"),
            "response_correct_on_time": pilot.paired_response(rows, arm_a, arm_b, "good"),
        }
    return paired


def combine_analysis(run_a: Path, run_live6k: Path, out_dir: Path,
                     cfg: dict | None = None) -> dict:
    """Combine five valid A phases with a corrected single-arm live6k run.

    A's original live6k phase is not in `phases.json` (it was aborted after the
    engine-core target bug); this function keeps only A's five valid phases and
    joins the pre-declared corrected 6k run.  No rows from the invalid 4k-target
    live6k phase are read.
    """
    cfg = cfg or load_config()
    run_a, run_live6k, out_dir = Path(run_a), Path(run_live6k), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_a, phases_a = pilot.build_rows(run_a)
    rows_b, phases_b = pilot.build_rows(run_live6k)
    rows_a = [row for row in rows_a if row["arm"] != "live6k"]
    phases_a = [phase for phase in phases_a if phase.get("policy_label") != "live6k"]
    rows = rows_a + rows_b
    phases = phases_a + phases_b
    labels = [item["label"] for item in cfg["design"]["arms"]]
    by_arm = {label: pilot.summarize([row for row in rows if row["arm"] == label])
              for label in labels}
    by_burst = {label: pilot.summarize([row for row in rows
                                        if row["arm"] == label and row["burst"]])
                for label in labels}
    by_cohort = {label: pilot.summarize([row for row in rows
                                         if row["arm"] == label and row["cohort"]])
                 for label in labels}
    by_tail = {label: pilot.summarize([row for row in rows
                                       if row["arm"] == label and row["tail"]])
               for label in labels}
    metrics_a = _phase_metrics(run_a, phases_a, cfg)
    metrics_b = _phase_metrics(run_live6k, phases_b, cfg)
    phase_metrics = metrics_a + metrics_b
    metrics_by_label = {item["policy_label"]: item for item in phase_metrics}
    for label, item in by_arm.items():
        item["worker_cuts"] = metrics_by_label.get(label, {}).get("cuts", 0)
        item["worker_cut_requests"] = metrics_by_label.get(label, {}).get("cut_requests", 0)
    paired = _paired_block(rows)
    result = {
        "generated_at": config.utc_now(),
        "run_dir": f"{run_a} + corrected {run_live6k}",
        "design": cfg["design"],
        "phases": phases,
        "phase_metrics": phase_metrics,
        "by_arm": by_arm, "by_burst": by_burst,
        "by_cohort": by_cohort, "by_tail": by_tail,
        "paired": paired,
        "rows": rows,
        "caveats": [
            "Screening extension, not a powered P3; the planned MDE is roughly 12-16 points.",
            "`live6k` was rerun after an engine-process target-propagation bug; the invalid 4k-target phase is excluded.",
            "Caps, missing outputs, late answers and errors stay in the denominator.",
            "Cut counts use worker.jsonl; request-record cut lists can miss a cut.",
            "The prefilled cohort is the most favorable natural case for a cut, not a representative load.",
        ],
    }
    result["decision"] = decide(result, cfg)
    config.write_json(out_dir / "prefill.json", result)
    config.write_json(out_dir / "summary.json", {
        "by_arm": by_arm, "by_burst": by_burst, "by_cohort": by_cohort,
        "by_tail": by_tail, "phase_metrics": phase_metrics,
        "decision": result["decision"],
    })
    with (out_dir / "paired.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["comparison", "field", "n", "mean_diff", "ci_low", "ci_high",
                         "wins", "losses", "ties"])
        for name, block in paired.items():
            for field in ("correct", "correct_on_time"):
                item = block[field]
                if not item.get("n"):
                    continue
                writer.writerow([name, field, item["n"], item["mean_diff"],
                                 item["ci_low"], item["ci_high"],
                                 item["wins"], item["losses"], item["ties"]])
    write_markdown(result, out_dir / "PREFILL.md")
    return result


def write_markdown(result: dict, path: Path) -> None:
    decision = result["decision"]
    fmt = pilot._fmt
    lines = ["# P3C prefilled-cohort cut stress", "",
             f"Generated: {result['generated_at']}", "",
             f"Run: `{result['run_dir']}`", "",
             "## Decision", "", f"**{decision['decision']}**", ""]
    lines += [f"- {reason}" for reason in decision["reasons"]]
    lines += ["", "### Validity", "", "| check | value |", "|---|---:|"]
    for key, value in decision["validity"].items():
        lines.append(f"| {key} | {fmt(value)} |")
    lines += ["", "## All signal", "",
              "| arm | correct / 180 | accuracy | correct-on-time | on-time rate | caps | worker cuts |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for label, item in result["by_arm"].items():
        lines.append(f"| {label} | {item['correct']} | {fmt(item['accuracy'])} | "
                     f"{item['correct_on_time']} | {fmt(item['good_rate'])} | {item['caps']} | "
                     f"{item.get('worker_cuts', item['cuts'])} |")
    for title, key in (("Cohort window", "by_cohort"),
                       ("Burst window", "by_burst"),
                       ("Tail window", "by_tail")):
        lines += ["", f"## {title}", "",
                  "| arm | correct | accuracy | correct-on-time | on-time rate |",
                  "|---|---:|---:|---:|---:|"]
        for label, item in result[key].items():
            lines.append(f"| {label} | {item['correct']} | {fmt(item['accuracy'])} | "
                         f"{item['correct_on_time']} | {fmt(item['good_rate'])} |")
    lines += ["", "## Paired comparisons", "",
              "`mean_diff` is arm A minus arm B at the question level.", "",
              "| comparison | field | n | mean diff | 95% CI | wins / losses / ties | sign p |",
              "|---|---|---:|---:|---|---:|---:|"]
    for name, block in result["paired"].items():
        for field in ("correct", "correct_on_time"):
            item = block[field]
            if not item.get("n"):
                continue
            lines.append(f"| {name} | {field} | {item['n']} | {item['mean_diff']:+.3f} | "
                         f"[{item['ci_low']:+.3f}, {item['ci_high']:+.3f}] | "
                         f"{item['wins']} / {item['losses']} / {item['ties']} | "
                         f"{item['sign_test']['p']:.4f} |")
    lines += ["", "## Phase metrics", "",
              "| phase | label | signal | miss rate | pressure >=8 | waiting p90 | cuts | cut after close | 4096 / 8192 admissions |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for item in result["phase_metrics"]:
        lines.append(f"| {item['phase']} | {item['policy_label']} | {item['measured_signal']} | "
                     f"{fmt(item['signal_miss_rate'])} | {fmt(item['pressure_fraction'])} | "
                     f"{fmt(item['waiting_p90'])} | {item['cuts']} | {item['cut_after_close']} | "
                     f"{item['admission_budget_short']} / {item['admission_budget_long']} |")
    lines += ["", "## Caveats", ""]
    lines += [f"- {caveat}" for caveat in result["caveats"]]
    lines.append("")
    Path(path).write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True,
                        choices=["build", "plan", "run", "analyse", "all"])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--trace-dir", type=Path)
    parser.add_argument("--config", type=Path,
                        help="override the pre-declaration (for the independent P3C-B replication)")
    args = parser.parse_args()
    if args.config:
        global CONFIG_PATH
        CONFIG_PATH = Path(args.config).resolve()
        pilot.PREFILL_CONFIG_PATH = CONFIG_PATH
    if args.stage == "build":
        entry = build_all(args.trace_dir)
        print(json.dumps({key: entry[key] for key in
                          ("file", "sha256", "cohort", "burst", "tail")}, indent=2))
        return
    if args.stage == "plan":
        phases = plan(trace_dir=args.trace_dir)
        print(json.dumps([{"phase": p["name"], "condition": p["condition"],
                           "arm": p["arm"], "label": p["policy_label"],
                           "cut_target": p["server_env"].get("LARB_CUT_TARGET"),
                           "requests": p["request_count"]} for p in phases], indent=2))
        return
    if args.out is None:
        raise SystemExit("--out is required for this stage")
    if args.stage in ("run", "all"):
        if args.stage == "all":
            build_all(args.trace_dir)
        run(args.out, args.trace_dir)
    if args.stage in ("analyse", "all"):
        result = analyse(args.out, args.out)
        print(json.dumps({"decision": result["decision"]["decision"],
                          "reasons": result["decision"]["reasons"]}, indent=2))


if __name__ == "__main__":
    main()

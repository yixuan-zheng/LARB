#!/usr/bin/env python3
"""P1 gate summaries from stored records (no GPU, no engine).

Reads the run directories produced by the P1 gate phases and the gate C/F
tools, grades the stored answers, and writes results/p1/gates.json with the
pass/fail decision for every gate.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from larb_scaled import analysis, config, grading  # noqa: E402


def load_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else default


def load_jsonl(path):
    rows = []
    if not Path(path).exists():
        return rows
    with Path(path).open() as handle:
        for line in handle:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def load_run(run_dir):
    run_dir = Path(run_dir)
    phases = load_json(run_dir / "phases.json", []) or []
    if not phases:
        # Rebuild from the per-phase records if a later server group wiped the
        # aggregate (older runner behaviour).
        phases = [json.loads(path.read_text())
                  for path in sorted((run_dir / "phases").glob("*.json"))]
    return dict(dir=run_dir, phases=phases,
                requests=analysis.load_requests(run_dir),
                scheduler=load_jsonl(run_dir / "scheduler.jsonl"),
                worker=load_jsonl(run_dir / "worker.jsonl"))


def grade_record(raw, use_math_verify):
    reference = raw.get("reference")
    result = grading.grade(raw.get("raw_output", ""), reference,
                           use_math_verify=use_math_verify)
    try:
        completion = analysis.audit_completion(raw, raw.get("cue_start"))
    except ValueError as exc:
        completion = dict(normal=False, reason=f"cue_mismatch:{exc}", complete=False,
                          thinking_tokens=0, answer_tokens=0, close_index=None,
                          forced=False)
    correct = bool(completion["normal"] and result["correct"])
    return dict(correct=correct, normal=completion["normal"], reason=completion["reason"],
                thinking_tokens=completion["thinking_tokens"],
                answer_tokens=completion["answer_tokens"],
                close_index=completion["close_index"], match=result["match"],
                extracted=result["extracted"], issue=result["issue"])


def by_identity(records, include_arm=False):
    """Index request records by (question, seed) rather than by runtime key.

    Runtime keys embed the condition, which differs between phases that must
    be compared (eager vs graph, legacy vs short, one budget vs another).
    """
    out = {}
    for raw in records.values():
        identity = (raw.get("question_id"), raw.get("seed"))
        if include_arm:
            identity = (raw.get("arm"),) + identity
        out[identity] = raw
    return out


def phase_records(run, phase_name=None):
    if phase_name is None:
        return run["requests"]
    return {key: raw for key, raw in run["requests"].items()
            if raw.get("phase") == phase_name}


def accuracy(records, use_math_verify):
    graded = [grade_record(raw, use_math_verify) for raw in records.values()]
    n = len(graded)
    correct = sum(row["correct"] for row in graded)
    caps = sum(row["reason"] == "answer_cap" for row in graded)
    answers = [row["answer_tokens"] for row in graded]
    thinking = [row["thinking_tokens"] for row in graded]
    return dict(n=n, correct=correct, accuracy=(correct / n if n else None),
                cap_rate=(caps / n if n else None),
                answer_tokens_median=(statistics.median(answers) if answers else None),
                thinking_tokens_median=(statistics.median(thinking) if thinking else None),
                graded=graded)


def paired_contract_difference(legacy, short, use_math_verify):
    lgrade = {key: grade_record(raw, use_math_verify) for key, raw in legacy.items()}
    sgrade = {key: grade_record(raw, use_math_verify) for key, raw in short.items()}
    pairs = []
    for key, row in lgrade.items():
        other = sgrade.get(key)
        if other is not None:
            pairs.append((1.0 if row["correct"] else 0.0,
                          1.0 if other["correct"] else 0.0))
    if not pairs:
        return dict(n=0, difference=None)
    diffs = [a - b for a, b in pairs]
    return dict(n=len(pairs), difference=statistics.mean(diffs),
                discordant=sum(1 for diff in diffs if diff != 0))



def gate_bridge(run, p1, mv):
    out = {}
    expected = p1["gates"]["bridge"]
    for arm, reference in expected["reference"].items():
        acc = accuracy(phase_records(run, f"bridge-{arm}"), mv)
        out[arm] = dict(n=acc["n"], correct=acc["correct"], accuracy=acc["accuracy"],
                        reference=reference,
                        difference=(acc["accuracy"] - reference
                                    if acc["accuracy"] is not None else None),
                        pass_=(acc["accuracy"] is not None and
                               abs(acc["accuracy"] - reference) <=
                               expected["tolerance_points"] / 100.0))
    out["pass"] = all(out[arm]["pass_"] for arm in expected["reference"])
    return out


def gate_mechanics(run):
    phases = {}
    for name in ("mechanics-fixed4k", "mechanics-fixed8k", "mechanics-r2-fixed8k",
                 "mechanics-forced"):
        records = phase_records(run, name)
        cue_exact = 0
        cue_mismatch = []
        offset_mismatch = []
        cut_after_close = 0
        cuts = 0
        natural = 0
        capped = 0
        for key, raw in records.items():
            cue = raw.get("cue_ids") or []
            ids = raw.get("token_ids") or []
            start = raw.get("cue_start")
            capped += 1 if raw.get("capped") else 0
            if start is None:
                natural += 1
            elif cue and ids[start:start + len(cue)] == cue:
                cue_exact += 1
                if raw.get("final_budget") is not None and start != raw["final_budget"]:
                    offset_mismatch.append(dict(key=key, cue_start=start,
                                                final_budget=raw["final_budget"]))
            else:
                cue_mismatch.append(key)
            close = None
            if raw.get("close_id") is not None:
                hits = [index for index, token in enumerate(ids)
                        if token == raw["close_id"]]
                close = hits[0] if len(hits) == 1 else None
            for cut in raw.get("cut_events", []) or []:
                cuts += 1
                if close is not None and cut.get("tokens", 0) >= close:
                    cut_after_close += 1
        phases[name] = dict(
            requests=len(records), cue_exact=cue_exact, cue_mismatch=cue_mismatch,
            offset_mismatch=offset_mismatch, natural_close=natural, cuts=cuts,
            capped=capped, cut_after_close=cut_after_close,
            preemption_peak=max((row.get("preemption_total") or 0
                                 for row in run["scheduler"]), default=0))
    phase_list = load_json(run["dir"] / "phases.json", []) or []
    planned = {phase["name"]: phase.get("request_count") for phase in phase_list}
    complete = all(len(phase_records(run, name)) == planned.get(name, 0)
                   for name in phases)
    forced = phases.get("mechanics-forced", {})
    forced_ok = (forced.get("cue_exact", 0) > 0 and forced.get("capped", 0) > 0)
    row_moves = sum(1 for row in run["worker"] if row.get("event") == "row_move")
    passed = (all(not block["cue_mismatch"] and not block["offset_mismatch"]
                  and block["cut_after_close"] == 0 for block in phases.values())
              and complete and forced_ok)
    return dict(phases=phases, planned=planned, all_records_present=complete,
                row_moves=row_moves, forced_cue_and_cap=forced_ok, pass_=bool(passed))


def gate_graphs(run):
    eager = by_identity(phase_records(run, "graphs-eager"))
    graph = by_identity(phase_records(run, "graphs-graph"))
    keys = sorted(set(eager) & set(graph))
    identical = 0
    cue_same = 0
    differences = []
    for key in keys:
        left, right = eager[key], graph[key]
        if left.get("token_ids") == right.get("token_ids"):
            identical += 1
        elif len(differences) < 10:
            first = next((index for index, (a, b) in enumerate(
                zip(left.get("token_ids") or [], right.get("token_ids") or [])) if a != b),
                min(len(left.get("token_ids") or []), len(right.get("token_ids") or [])))
            differences.append(dict(key=key, first_divergence=first,
                                    eager_tokens=len(left.get("token_ids") or []),
                                    graph_tokens=len(right.get("token_ids") or [])))
        if left.get("cue_start") == right.get("cue_start"):
            cue_same += 1

    def service(records):
        values = [raw["finished"] - raw["received"] for raw in records.values()
                  if raw.get("finished") is not None and raw.get("received") is not None]
        return statistics.mean(values) if values else None

    return dict(n=len(keys), tokens_identical=identical, cue_position_identical=cue_same,
                differences=differences,
                eager_mean_service_s=service(eager), graph_mean_service_s=service(graph),
                pass_=bool(keys and cue_same == len(keys) and identical == len(keys)))


def gate_contract(run, mv):
    summary = {}
    for contract in ("legacy", "short_boxed"):
        for arm in ("fixed4k", "fixed8k"):
            name = f"contract-{contract}-{arm}"
            acc = accuracy(phase_records(run, name), mv)
            summary[name] = {key: acc[key] for key in
                             ("n", "correct", "accuracy", "cap_rate",
                              "answer_tokens_median")}
    legacy = {}
    short = {}
    for arm in ("fixed4k", "fixed8k"):
        legacy.update(by_identity(phase_records(run, f"contract-legacy-{arm}"), True))
        short.update(by_identity(phase_records(run, f"contract-short_boxed-{arm}"), True))
    paired = paired_contract_difference(legacy, short, mv)
    legacy_caps = [value["cap_rate"] for key, value in summary.items()
                   if key.startswith("contract-legacy") and value["cap_rate"] is not None]
    short_caps = [value["cap_rate"] for key, value in summary.items()
                  if key.startswith("contract-short") and value["cap_rate"] is not None]
    short_answers = [value["answer_tokens_median"] for key, value in summary.items()
                     if key.startswith("contract-short")
                     and value["answer_tokens_median"] is not None]
    legacy_cap = statistics.mean(legacy_caps) if legacy_caps else None
    short_cap = statistics.mean(short_caps) if short_caps else None
    short_answer = statistics.mean(short_answers) if short_answers else None
    passed = bool(paired["difference"] is not None and abs(paired["difference"]) <= 0.02
                  and legacy_cap is not None and short_cap is not None
                  and short_cap < legacy_cap
                  and short_answer is not None and short_answer < 256)
    return dict(phases=summary, paired=paired, legacy_cap_rate=legacy_cap,
                short_cap_rate=short_cap, short_answer_tokens_median=short_answer,
                pass_=passed, selected=("short_boxed" if passed else "legacy"))


def gate_slope(run, mv):
    out = {}
    for trace in ("gate-screen", "gate-preview"):
        accs = {}
        values = {}
        for arm in ("fixed4k", "fixed6k", "fixed8k"):
            records = phase_records(run, f"slope-{trace}-{arm}")
            acc = accuracy(records, mv)
            accs[arm] = {key: acc[key] for key in
                         ("n", "correct", "accuracy", "cap_rate",
                          "thinking_tokens_median")}
            values[arm] = {identity: grade_record(raw, mv)["extracted"]
                           for identity, raw in by_identity(records).items()}
        gain = (accs["fixed8k"]["accuracy"] - accs["fixed4k"]["accuracy"]
                if accs["fixed8k"]["accuracy"] is not None
                and accs["fixed4k"]["accuracy"] is not None else None)
        keys = sorted(set(values["fixed4k"]) & set(values["fixed8k"]))
        changed = sum(1 for key in keys if values["fixed4k"][key] != values["fixed8k"][key])
        change_fraction = changed / len(keys) if keys else None
        acc8 = accs["fixed8k"]["accuracy"]
        passed = bool(gain is not None and (gain >= 0.08 or (change_fraction or 0) >= 0.10)
                      and acc8 is not None and 0.35 <= acc8 <= 0.75
                      and (accs["fixed8k"]["cap_rate"] or 0) <= 0.20
                      and (accs["fixed8k"]["thinking_tokens_median"] or 0) <= 8192)
        out[trace] = dict(arms=accs, gain_4k_to_8k=gain,
                          answer_change_fraction=change_fraction, pass_=passed)
    out["pass"] = out["gate-preview"]["pass_"]
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=ROOT / "results/p1/runs")
    parser.add_argument("--sweep", type=Path, default=ROOT / "results/p1/sweep")
    parser.add_argument("--calibration", type=Path, default=ROOT / "results/p1/calibration")
    parser.add_argument("--out", type=Path, default=ROOT / "results/p1/gates.json")
    parser.add_argument("--no-math-verify", action="store_true")
    args = parser.parse_args()
    try:
        import math_verify  # noqa: F401
        use_math_verify = not args.no_math_verify
    except ImportError:
        use_math_verify = False
    result = dict(generated_at=config.utc_now(),
                  grader=("math_verify" if use_math_verify else "exact_match"),
                  gates={})
    if (args.runs / "bridge").exists():
        result["gates"]["bridge"] = gate_bridge(load_run(args.runs / "bridge"),
                                                config.load_p1_gates(), use_math_verify)
    if (args.runs / "mechanics").exists():
        result["gates"]["mechanics"] = gate_mechanics(load_run(args.runs / "mechanics"))
    if (args.runs / "graphs").exists():
        result["gates"]["graphs"] = gate_graphs(load_run(args.runs / "graphs"))
    if (args.runs / "contract").exists():
        result["gates"]["contract"] = gate_contract(load_run(args.runs / "contract"),
                                                    use_math_verify)
    if (args.runs / "slope").exists():
        result["gates"]["slope"] = gate_slope(load_run(args.runs / "slope"),
                                             use_math_verify)
    sweep = load_json(args.sweep / "throughput.json")
    if sweep:
        result["gates"]["throughput"] = dict(points=sweep.get("points"),
                                             recommendation=sweep.get("recommendation"))
    calibration = load_json(args.calibration / "calibration.json")
    if calibration:
        result["gates"]["calibration"] = calibration
    config.write_json(args.out, result)
    print(json.dumps({name: (block.get("pass_") if isinstance(block, dict) else None)
                      for name, block in result["gates"].items()}, indent=2))
    return result


if __name__ == "__main__":
    main()

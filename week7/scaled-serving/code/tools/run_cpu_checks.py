#!/usr/bin/env python3
"""Run the CPU-only P0 checks and write one consolidated status artifact."""
import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from larb_scaled import config, stats, workload  # noqa: E402


def run_tests():
    env = dict(**__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT / "code") + ":" + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-m", "unittest", "discover",
                             "-s", str(ROOT / "code/tests"), "-p", "test_*.py"],
                            cwd=str(ROOT.parent.parent), env=env,
                            capture_output=True, text=True)
    log = ROOT / "logs/p0/unittest.log"
    log.write_text(result.stdout + result.stderr)
    return {"passed": result.returncode == 0, "returncode": result.returncode,
            "output_tail": (result.stdout + result.stderr)[-2000:]}


def run_synthetic():
    env = dict(**__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT / "code") + ":" + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, str(ROOT / "code/tools/synthetic_rehearsal.py")],
                            cwd=str(ROOT.parent.parent), env=env,
                            capture_output=True, text=True)
    log = ROOT / "logs/p0/synthetic.log"
    log.write_text(result.stdout + result.stderr)
    return result.returncode == 0


def check_manifests():
    raw = json.loads((ROOT / "data/raw/manifest.json").read_text())
    expected = 12
    return {
        "datasets": len(raw.get("datasets", [])),
        "expected_datasets": expected,
        "failures": raw.get("failures", []),
        "licenses_recorded": sum(1 for item in raw.get("datasets", []) if item.get("license")),
        "source_hashes": sum(1 for item in raw.get("datasets", []) if item.get("source_sha256")),
        "rows": {item["dataset"]: item.get("row_count") for item in raw.get("datasets", [])},
        "ok": len(raw.get("datasets", [])) == expected and not raw.get("failures"),
    }


def check_cohort():
    cohort = config.load_cohort()
    questions = workload.load_questions()
    counts = cohort["counts"]
    missing = [qid for qid in cohort["main_ids"] + cohort["bridge_ids"] +
               cohort["screen_ids"] + cohort["filler_ids"] if qid not in questions]
    return {
        "counts": counts,
        "missing_questions": missing,
        "main_in_range": 200 <= counts["main"] <= 246,
        "bridge_is_30": counts["bridge"] == 30,
        "screen_is_48": counts["screen"] == 48,
        "filler_at_least_50": counts["filler"] >= 50,
        "questions_sha256": cohort.get("questions_sha256"),
        "ok": not missing and 200 <= counts["main"] <= 246 and counts["bridge"] == 30
              and counts["screen"] == 48 and counts["filler"] >= 50,
    }


def check_traces():
    protocol = config.load_protocol()
    cohort = config.load_cohort()
    questions = workload.load_questions()
    manifest = json.loads((ROOT / "artifacts/traces/manifest.json").read_text())
    results = {}
    ok = True
    mapping = {"gate-bridge": "bridge_ids", "gate-screen": "screen_ids",
               "gate-preview": "preview_ids", "gate-contract": "screen_ids",
               "gate-mechanics": "screen_ids"}
    for condition in list(workload.CONDITIONS) + list(mapping):
        path = ROOT / "artifacts/traces" / f"{condition}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        allowed = None if condition in workload.CONDITIONS else cohort[mapping[condition]]
        try:
            workload.validate_trace(rows, condition, protocol, cohort, questions,
                                    allowed_signal_ids=allowed)
            valid = True
        except Exception:
            valid = False
            logging.exception("trace validation failed: %s", condition)
        summary = workload.trace_summary(rows)
        expected_hash = manifest["traces"].get(condition, {}).get("sha256")
        actual_hash = config.digest(path)
        results[condition] = {"valid": valid, "sha256_match": expected_hash == actual_hash,
                              "summary": summary, "sha256": actual_hash}
        ok = ok and valid and expected_hash == actual_hash
    return {"traces": results, "ok": ok}


def power_table():
    rows = []
    for questions in (200, 215, 220, 246, 500, 800):
        for seeds in (4, 6):
            for icc in (0.2, 0.4, 0.6):
                n_eff = stats.effective_n(questions, seeds, icc)
                rows.append(dict(questions=questions, seeds=seeds, icc=icc,
                                 effective_pairs=n_eff,
                                 mde_points_disc20=100 * stats.paired_mde(n_eff, 0.20)))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    (ROOT / "logs/p0").mkdir(parents=True, exist_ok=True)
    (ROOT / "results/p0").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / "logs/p0/cpu_checks.log"),
                                  logging.StreamHandler(sys.stdout)])
    tests = {"skipped": True, "passed": None} if args.skip_tests else run_tests()
    synthetic_ok = run_synthetic()
    manifests = check_manifests()
    cohort = check_cohort()
    traces = check_traces()
    power = power_table()
    protocol_ok = True
    try:
        config.validate_all()
    except Exception:
        protocol_ok = False
        logging.exception("protocol validation failed")
    status = {
        "generated_at": config.utc_now(),
        "tests": tests,
        "synthetic": {"ok": synthetic_ok},
        "manifests": manifests,
        "cohort": cohort,
        "traces": traces,
        "protocol_ok": protocol_ok,
        "power": power,
        "overall_ok": bool((tests.get("passed") or tests.get("skipped")) and synthetic_ok
                           and manifests["ok"] and cohort["ok"] and traces["ok"] and protocol_ok),
    }
    config.write_json(ROOT / "results/p0/cpu_checks.json", status)
    config.write_json(ROOT / "results/p0/power.json", power)
    freeze = config.freeze_manifest(extra={"p0_status": "results/p0/cpu_checks.json"})
    status["freeze"] = freeze
    config.write_json(ROOT / "results/p0/cpu_checks.json", status)
    print(json.dumps({k: status[k] for k in ("generated_at", "tests", "manifests",
                                             "cohort", "protocol_ok", "overall_ok")},
                     indent=2))
    if not status["overall_ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()


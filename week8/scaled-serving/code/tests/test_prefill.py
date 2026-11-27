"""CPU tests for the P3C prefilled-cohort cut-stress extension."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import larb_week8  # noqa: E402,F401
from larb_week8 import pilot, prefill  # noqa: E402


class PrefillShapeTest(unittest.TestCase):
    def test_trace_has_full_cohort_and_burst(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = prefill.load_config()
            entry = pilot.build_prefill_trace(cfg, Path(folder))
            self.assertEqual(entry["cohort"], 32)
            self.assertEqual(entry["burst"], 64)
            self.assertEqual(entry["summary"]["signal"], 180)
            self.assertEqual(entry["summary"]["filler"], 78)
            self.assertEqual(entry["summary"]["signal_questions"], 60)
            self.assertEqual(entry["summary"]["seeds_per_question"], 3.0)
            rows = pilot.load_trace(Path(entry["file"]))
            self.assertTrue(all(row["deadline_s"] == 240.0 for row in rows))
            cohort = [row for row in rows if row["arrival_s"] < entry["cohort_end_s"]]
            self.assertEqual(len(cohort), 32)
            self.assertTrue(all(row["class"] == "signal" for row in cohort))
            burst = [row for row in rows
                     if entry["burst_start_s"] <= row["arrival_s"] < entry["burst_end_s"]]
            self.assertGreaterEqual(len(burst), 60)
            self.assertGreaterEqual(sum(row["class"] == "signal" for row in burst), 25)

    def test_plan_has_six_arms_and_cut_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            trace_dir = Path(folder)
            prefill.build_all(trace_dir)
            phases = prefill.plan(trace_dir=trace_dir)
            self.assertEqual(len(phases), 6)
            by_label = {phase["policy_label"]: phase for phase in phases}
            self.assertEqual(by_label["fixed4k"]["arm"], "fixed4k")
            self.assertEqual(by_label["fixed6k"]["arm"], "fixed6k")
            self.assertEqual(by_label["fixed8k"]["arm"], "fixed8k")
            self.assertEqual(by_label["arrival"]["arm"], "arrival")
            self.assertEqual(by_label["live4k"]["arm"], "live")
            self.assertEqual(by_label["live6k"]["arm"], "live")
            self.assertEqual(by_label["live4k"]["server_env"]["LARB_CUT_TARGET"], "4096")
            self.assertEqual(by_label["live6k"]["server_env"]["LARB_CUT_TARGET"], "6096")
            self.assertTrue(all(phase["request_count"] == 258 for phase in phases))


def _result(go: bool = True) -> dict:
    labels = ["fixed4k", "fixed6k", "fixed8k", "arrival", "live4k", "live6k"]
    phases = [{"name": label, "policy_label": label, "injection_valid": True,
               "errors": 0, "arm": "live" if label.startswith("live") else label}
              for label in labels]
    metrics = []
    for label in labels:
        metrics.append({"phase": label, "policy_label": label, "arm": "live" if label.startswith("live") else label,
                        "cuts": 5 if label.startswith("live") else 0,
                        "cut_after_close": 0, "admission_budget_short": 10,
                        "admission_budget_long": 10})
    paired = {
        "live4k_vs_arrival": {"correct": {"mean_diff": 0.02 if go else -0.01},
                              "correct_on_time": {"mean_diff": 0.02 if go else -0.01}},
        "live6k_vs_arrival": {"correct": {"mean_diff": 0.08 if go else -0.01},
                              "correct_on_time": {"mean_diff": 0.08 if go else -0.01}},
        "live6k_vs_fixed8k": {"correct": {"mean_diff": -0.05}, "correct_on_time": {"mean_diff": 0.05}},
        "live4k_vs_fixed8k": {"correct": {"mean_diff": -0.10}, "correct_on_time": {"mean_diff": 0.02}},
    }
    return {"by_arm": {label: {"planned": 180, "present": 180, "missing": 0}
                       for label in labels},
            "phases": phases, "phase_metrics": metrics, "paired": paired}


class PrefillDecisionTest(unittest.TestCase):
    def test_go_when_best_live_beats_arrival(self):
        decision = prefill.decide(_result(True))
        self.assertEqual(decision["decision"], "go_cut")
        self.assertEqual(decision["best_live_label"], "live6k")

    def test_stop_when_no_live_beats_arrival(self):
        decision = prefill.decide(_result(False))
        self.assertEqual(decision["decision"], "stop_cut")

    def test_admission_only_branch(self):
        cfg = prefill.load_config()
        cfg["design"]["arms"] = [
            {"label": label, "arm": label, "cut_target": 4096}
            for label in ("fixed4k", "fixed6k", "fixed8k", "arrival")
        ]
        labels = [item["label"] for item in cfg["design"]["arms"]]
        phases = [{"name": label, "policy_label": label,
                   "injection_valid": True, "errors": 0, "arm": label}
                  for label in labels]
        metrics = [{"phase": label, "policy_label": label, "arm": label,
                    "cuts": 0, "cut_after_close": 0,
                    "admission_budget_short": 0, "admission_budget_long": 0}
                   for label in labels]
        result = {"by_arm": {label: {"planned": 180, "present": 180, "missing": 0}
                             for label in labels},
                  "phases": phases, "phase_metrics": metrics, "paired": {}}
        decision = prefill.decide(result, cfg)
        self.assertEqual(decision["decision"], "admission_only")
        self.assertTrue(decision["validity"]["pass"])


if __name__ == "__main__":
    unittest.main()

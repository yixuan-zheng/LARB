"""CPU tests for the P2C quality-first burst pilot.

No GPU, no vLLM.  These tests pin the pre-declared trace shape, the phase plan
and the fail-fast decision arithmetic.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import larb_week8  # noqa: E402,F401
from larb_week8 import pilot  # noqa: E402


def _validity(passed: bool = True) -> dict:
    return {
        "coverage_ok": passed, "injection_ok": passed, "errors_ok": passed,
        "live_cuts": 9 if passed else 0,
        "live_each_phase_has_cut": passed,
        "live_pressure_fraction_max": 0.5 if passed else 0.0,
        "cut_after_close": 0,
        "live_admission_short": 20 if passed else 0,
        "live_admission_long": 20 if passed else 0,
        "fixed_arm_cuts": 0,
        "pass": passed,
    }


def _result(stage: str = "a", validity: bool = True, slope: float = 0.15,
            live_good: float = 0.05, live_correct: float = 0.05,
            live_vs_8k: float = -0.05) -> dict:
    traces = ["pilot-burst-a"] if stage == "a" else ["pilot-burst-a", "pilot-burst-b"]
    phases = []
    for trace in traces:
        for arm in pilot.ARMS:
            phases.append({"name": f"{trace}-{arm}", "pilot_trace": trace,
                           "arm": arm, "injection_valid": True, "errors": 0})
    phase_metrics = [{"phase": p["name"], "arm": p["arm"],
                      "cuts": 9 if (validity and p["arm"] == "live") else 0,
                      "cut_after_close": 0,
                      "pressure_fraction": 0.5 if (validity and p["arm"] == "live") else 0.0,
                      "admission_budget_short": 20 if (validity and p["arm"] == "live") else 0,
                      "admission_budget_long": 20 if (validity and p["arm"] == "live") else 0}
                     for p in phases]
    paired = {
        "fixed4k_vs_fixed8k": {"correct": {"mean_diff": -slope},
                               "correct_on_time": {"mean_diff": -slope}},
        "live_vs_fixed4k": {"correct": {"mean_diff": live_correct},
                            "correct_on_time": {"mean_diff": live_good}},
        "live_vs_fixed8k": {"correct": {"mean_diff": live_vs_8k},
                            "correct_on_time": {"mean_diff": live_vs_8k}},
    }
    return {"by_arm": {arm: {"planned": 120, "present": 120, "accuracy": 0.5}
                       for arm in pilot.ARMS},
            "paired": paired, "phases": phases, "phase_metrics": phase_metrics,
            "validity": _validity(validity)}


class TraceShapeTest(unittest.TestCase):
    def test_two_traces_have_the_declared_shape(self):
        cfg = pilot.load_config()
        spec = pilot.trace_specs("a", cfg)[0]
        with tempfile.TemporaryDirectory() as folder:
            entry = pilot.build_trace(spec, cfg, Path(folder))
            self.assertEqual(entry["signal"], 120)
            self.assertEqual(entry["filler"], 52)
            self.assertEqual(entry["questions"], 60)
            self.assertEqual(entry["seeds_per_question"], 2.0)
            self.assertGreaterEqual(entry["burst_rows"], 60)
            self.assertLessEqual(entry["burst_rows"], 70)
            self.assertGreaterEqual(entry["burst_signal"], 35)
            rows = pilot.load_trace(Path(entry["file"]))
            self.assertTrue(all(row["deadline_s"] == 240.0 for row in rows))
            self.assertTrue(all(row["condition"] == "burst" for row in rows))

    def test_plan_has_four_arms_per_trace(self):
        with tempfile.TemporaryDirectory() as folder:
            trace_dir = Path(folder)
            pilot.build_all("both", trace_dir)
            phases = pilot.plan("both", trace_dir=trace_dir)
            self.assertEqual(len(phases), 8)
            self.assertEqual({p["arm"] for p in phases}, set(pilot.ARMS))
            self.assertTrue(all(p["deadline_s"] == 240.0 for p in phases))
            self.assertTrue(all(p["request_count"] == 172 for p in phases))


class DecisionTest(unittest.TestCase):
    def test_stage_a_continue(self):
        decision = pilot.decide(_result("a"))
        self.assertEqual(decision["decision"], "stage_a_continue")
        self.assertAlmostEqual(decision["slope_fixed8k_minus_fixed4k_accuracy"], 0.15)

    def test_stage_a_stops_on_flat_slope(self):
        decision = pilot.decide(_result("a", slope=0.02))
        self.assertEqual(decision["decision"], "stop_slope")

    def test_stage_a_stops_on_invalid_manipulation(self):
        decision = pilot.decide(_result("a", validity=False))
        self.assertEqual(decision["decision"], "invalid")

    def test_final_go(self):
        decision = pilot.decide(_result("both", live_good=0.10, live_correct=0.10))
        self.assertEqual(decision["decision"], "go")

    def test_final_stops_when_live_is_worse_than_fixed4k(self):
        decision = pilot.decide(_result("both", live_good=-0.03, live_correct=-0.03))
        self.assertEqual(decision["decision"], "stop_final")


class PairedTest(unittest.TestCase):
    def _rows(self):
        rows = []
        for qid in ("q1", "q2", "q3", "q4"):
            for arm, correct, good in (("fixed4k", False, False),
                                       ("fixed8k", True, True),
                                       ("live", True, True)):
                rows.append({"arm": arm, "question_id": qid, "seed": 1,
                             "trace": "t", "scored": True,
                             "correct": correct, "good": good,
                             "extracted": str(int(correct))})
        return rows

    def test_paired_question_uses_arm_a_minus_arm_b(self):
        item = pilot.paired_question(self._rows(), "live", "fixed4k", "correct")
        self.assertEqual(item["n"], 4)
        self.assertAlmostEqual(item["mean_diff"], 1.0)

    def test_paired_response_counts_conversions(self):
        item = pilot.paired_response(self._rows(), "fixed4k", "fixed8k", "correct")
        self.assertEqual(item["n"], 4)
        self.assertEqual(item["b_only"], 4)
        self.assertAlmostEqual(item["gain"], -1.0)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from larb_scaled import analysis


CUE = [7, 9, 6]


def trace_row(qid="q1", seed=1):
    return {"trace_id": f"low--signal--{qid}--{seed}", "condition": "low", "class": "signal",
            "question_id": qid, "seed": seed, "arrival_s": 0.0, "deadline_s": 100.0,
            "prompt_sha256": "x", "reference": "42", "source": "test", "exposure": "fresh",
            "answer_type": "integer", "scored": True, "initial_budget": None}


def raw_record(key, correct=True, capped=False):
    answer = [2, 2, 2] if correct else [3]
    if capped:
        answer = [2] * 9
    return {
        "key": key, "complete": True, "token_ids": [1] * 100 + CUE + answer + [0],
        "cue_ids": CUE, "close_id": 9, "eos_id": 0, "answer_cap": 8,
        "raw_output": "\\boxed{42}" if correct else "\\boxed{41}",
        "cue_start": 100, "finished": 50.0, "scheduler_start": 0.0,
        "initial_budget": 8192, "final_budget": 4096, "cut_events": [{"tokens": 512}],
        "preemptions": 0, "waiting_at_arrival": 8, "pressure_fraction": 0.2,
    }


class AnalysisTests(unittest.TestCase):
    def phase(self, arm="live"):
        return {"name": f"low-{arm}", "condition": "low", "arm": arm, "epoch": 0.0,
                "horizon_s": 200.0, "deadline_s": 100.0, "last_arrival_s": 0.0}

    def test_correct_and_on_time(self):
        trace = trace_row()
        key = analysis.runtime_key("low", "live", trace)
        rows = analysis.build_rows([trace], self.phase("live"), {key: raw_record(key)})
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row["correct"])
        self.assertTrue(row["timely"])
        self.assertTrue(row["good"])
        self.assertEqual(row["thinking_tokens"], 100)
        self.assertEqual(row["answer_tokens"], 5)
        self.assertEqual(row["cuts"], 1)
        summary = analysis.summarize_phase(rows, self.phase("live"))
        self.assertEqual(summary["correct_on_time"], 1)
        self.assertEqual(summary["planned"], 1)

    def test_missing_is_failure(self):
        trace = trace_row()
        rows = analysis.build_rows([trace], self.phase("live"), {})
        self.assertFalse(rows[0]["present"])
        self.assertFalse(rows[0]["good"])
        self.assertEqual(rows[0]["issue"], "missing")

    def test_cap_is_failure(self):
        trace = trace_row()
        key = analysis.runtime_key("low", "live", trace)
        rows = analysis.build_rows([trace], self.phase("live"), {key: raw_record(key, capped=True)})
        self.assertFalse(rows[0]["normal"])
        self.assertEqual(rows[0]["reason"], "answer_cap")
        self.assertFalse(rows[0]["good"])

    def test_question_pairing(self):
        rows = [
            {"condition": "low", "arm": "live", "question_id": "q1", "scored": True, "good": True},
            {"condition": "low", "arm": "live", "question_id": "q1", "scored": True, "good": False},
            {"condition": "low", "arm": "fixed4k", "question_id": "q1", "scored": True, "good": False},
            {"condition": "low", "arm": "fixed4k", "question_id": "q1", "scored": True, "good": False},
            {"condition": "low", "arm": "live", "question_id": "q2", "scored": True, "good": True},
            {"condition": "low", "arm": "fixed4k", "question_id": "q2", "scored": True, "good": True},
        ]
        pairs = analysis.paired_table(rows, "live", "fixed4k")
        self.assertEqual(len(pairs), 2)
        q1 = next(pair for pair in pairs if pair["question_id"] == "q1")
        self.assertAlmostEqual(q1["a"], 0.5)
        self.assertAlmostEqual(q1["b"], 0.0)
        summary = analysis.paired_summary(pairs, resamples=1000)
        self.assertEqual(summary["n"], 2)
        self.assertGreater(summary["pooled"]["mean"], 0)

    def test_analyze_run_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "requests").mkdir()
            trace = trace_row()
            (root / "trace.jsonl").write_text(json.dumps(trace) + "\n")
            phases = []
            for arm in ("live", "fixed4k"):
                phase = self.phase(arm)
                phase["trace_file"] = "trace.jsonl"
                phases.append(phase)
                key = analysis.runtime_key("low", arm, trace)
                (root / "requests" / f"{key}.json").write_text(
                    json.dumps(raw_record(key, correct=(arm == "live"))))
            (root / "phases.json").write_text(json.dumps(phases))
            result = analysis.analyze_run(root)
            self.assertEqual(len(result["phases"]), 2)
            self.assertIn("fixed4k_vs_live", result["paired"])
            self.assertEqual(result["paired"]["fixed4k_vs_live"]["summary"]["n"], 1)
            self.assertTrue((root / "analysis" / "analysis.json").exists())


if __name__ == "__main__":
    unittest.main()

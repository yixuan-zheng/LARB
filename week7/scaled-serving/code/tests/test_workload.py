import hashlib
import json
import unittest
from pathlib import Path

from larb_scaled import config, workload


def make_question(qid, role="main", pool="MathArena/aime_2026", exposure="fresh", answer="7"):
    problem = f"Find the value for {qid}."
    prompt = problem + "\nPlease put your final answer within \\boxed{}."
    return {
        "question_id": qid, "role": role, "pool": pool, "problem": problem,
        "answer": answer, "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "exposure": exposure, "answer_type": "integer",
    }


class WorkloadTests(unittest.TestCase):
    def setUp(self):
        self.protocol = config.load_protocol()
        main = [make_question(f"main-{i:03d}") for i in range(20)]
        bridge = [make_question(f"bridge-{i:02d}", role="bridge",
                                pool="MathArena/aime_2025", exposure="exposed") for i in range(2)]
        filler = [make_question(f"filler-{i:02d}", role="filler",
                                pool="HuggingFaceH4/MATH-500", exposure="exposed") for i in range(10)]
        self.questions = {q["question_id"]: q for q in main + bridge + filler}
        self.cohort = {
            "main_ids": [q["question_id"] for q in main],
            "preview_ids": [],
            "bridge_ids": [q["question_id"] for q in bridge],
            "screen_ids": [],
            "filler_ids": [q["question_id"] for q in filler],
            "main_pool": main,
        }

    def test_build_trace_is_valid_and_deterministic(self):
        first = workload.build_trace("low", self.cohort, self.questions, self.protocol,
                                     signal_limit=5, seeds=2, seed=7)
        second = workload.build_trace("low", self.cohort, self.questions, self.protocol,
                                      signal_limit=5, seeds=2, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 15)
        self.assertEqual(sum(row["class"] == "signal" for row in first), 10)
        self.assertEqual(sum(row["class"] == "filler" for row in first), 5)
        self.assertTrue(all(row["scored"] for row in first if row["class"] == "signal"))
        self.assertTrue(all(not row["scored"] for row in first if row["class"] == "filler"))
        self.assertEqual([row["arrival_s"] for row in first],
                         sorted(row["arrival_s"] for row in first))
        self.assertEqual(len({row["trace_id"] for row in first}), len(first))

    def test_gate_trace_uses_bridge_ids(self):
        rows = workload.build_gate_trace("gate-bridge", "bridge_ids", 2, self.cohort,
                                         self.questions, self.protocol)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["condition"] == "gate-bridge" for row in rows))
        self.assertTrue(all(row["question_id"].startswith("bridge-") for row in rows))

    def test_real_trace_integration_if_present(self):
        path = config.ARTIFACTS_DIR / "traces/low.jsonl"
        cohort_path = config.ARTIFACTS_DIR / "cohort.json"
        if not path.exists() or not cohort_path.exists():
            self.skipTest("P0 traces not built")
        cohort = json.loads(cohort_path.read_text())
        questions = workload.load_questions()
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        workload.validate_trace(rows, "low", self.protocol, cohort, questions)


if __name__ == "__main__":
    unittest.main()

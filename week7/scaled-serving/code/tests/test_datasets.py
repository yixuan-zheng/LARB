import hashlib
import unittest

from larb_scaled.datasets import mark_exclusions, select_cohort, validate_questions


def question(qid, role="main", pool="MathArena/aime_2026", exposure="fresh",
             problem=None, answer="7"):
    problem = problem or f"Find $x$ for {qid}."
    return {
        "question_id": qid, "role": role, "pool": pool, "problem": problem,
        "answer": answer, "prompt": problem + "\nPlease put your final answer within \\boxed{}.",
        "prompt_sha256": hashlib.sha256(
            (problem + "\nPlease put your final answer within \\boxed{}.").encode()).hexdigest(),
        "exposure": exposure, "answer_type": "integer" if answer.isdigit() else "expression",
    }


class DatasetTests(unittest.TestCase):
    def test_exclusions_and_bridge_override(self):
        rows = [
            question("main-1", problem="Find $x$."),
            question("main-2", problem="Find $x$."),
            question("main-3", problem="See [asy] draw((0,0)--(1,1)); [/asy] Find $x$."),
            question("main-4", problem="Prove that the sum is even."),
            question("bridge-1", role="bridge", pool="MathArena/aime_2025",
                     problem="See [asy] diagram. Find $x$."),
        ]
        kept, excluded = mark_exclusions(rows, {})
        by_id = {row["question_id"]: row for row in rows}
        self.assertFalse(by_id["main-2"]["eligible"])  # duplicate text
        self.assertFalse(by_id["main-3"]["eligible"])
        self.assertFalse(by_id["main-4"]["eligible"])
        self.assertTrue(by_id["bridge-1"]["eligible"])
        self.assertEqual(by_id["bridge-1"]["bridge_flag"], "diagram_dependent")
        self.assertEqual(len(kept), 2)
        self.assertGreaterEqual(len(excluded), 3)

    def test_cohort_selection_is_deterministic(self):
        rows = [question(f"main-{i:03d}", exposure="fresh" if i % 2 else "recent")
                for i in range(210)]
        rows += [question(f"bridge-{i:02d}", role="bridge",
                          pool="MathArena/aime_2025", exposure="exposed") for i in range(2)]
        rows += [question(f"screen-a-{i:02d}", role="screen",
                          pool="MathArena/aime_2023_I", exposure="exposed") for i in range(30)]
        rows += [question(f"screen-h-{i:02d}", role="screen",
                          pool="MathArena/hmmt_feb_2024", exposure="exposed") for i in range(30)]
        rows += [question(f"filler-{i:02d}", role="filler",
                          pool="HuggingFaceH4/MATH-500", exposure="exposed") for i in range(10)]
        mark_exclusions(rows, {})
        first = select_cohort(rows, salt="test-salt")
        second = select_cohort(rows, salt="test-salt")
        self.assertEqual(first["main_ids"], second["main_ids"])
        self.assertEqual(first["counts"]["preview"], 24)
        self.assertEqual(first["counts"]["main"], 186)
        self.assertEqual(first["counts"]["bridge"], 2)
        self.assertEqual(first["counts"]["screen"], 48)
        self.assertEqual(first["counts"]["filler"], 10)
        self.assertFalse(set(first["preview_ids"]) & set(first["main_ids"]))

    def test_validate_questions(self):
        rows = [question("q1")]
        mark_exclusions(rows, {})
        self.assertTrue(validate_questions(rows))
        broken = [dict(rows[0], prompt_sha256="bad")]
        with self.assertRaises(ValueError):
            validate_questions(broken)


if __name__ == "__main__":
    unittest.main()

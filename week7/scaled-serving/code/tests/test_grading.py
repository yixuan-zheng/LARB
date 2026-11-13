import unittest

from larb_scaled import grading


class GradingTests(unittest.TestCase):
    def test_extract_integer_and_nested_expression(self):
        self.assertEqual(grading.extract_boxed("work \\boxed{42}")["value"], "42")
        self.assertEqual(grading.extract_boxed("work \\boxed{\\frac{1}{2}}")["value"],
                         "\\frac{1}{2}")
        self.assertEqual(grading.extract_boxed("work \\boxed{\\left(3,\\frac{\\pi}{2}\\right)}")["value"],
                         "\\left(3,\\frac{\\pi}{2}\\right)")

    def test_missing_and_grouped(self):
        self.assertEqual(grading.extract_boxed("no box")["issue"], "missing_complete_box")
        grouped = "\\boxed{1}, \\boxed{2}"
        self.assertEqual(grading.extract_boxed(grouped)["issue"],
                         "multiple_grouped_final_boxes")

    def test_after_thinking_uses_last_close(self):
        text = "old </think> \\boxed{1} </think> \\boxed{2}"
        self.assertEqual(grading.extract_boxed(text)["value"], "2")

    def test_exact_and_integer(self):
        self.assertTrue(grading.exact_match("042", "42"))
        self.assertTrue(grading.exact_match("\\frac{1}{2}", "\\frac{1}{2}"))
        self.assertFalse(grading.exact_match("\\frac{1}{2}", "\\frac12"))
        self.assertFalse(grading.exact_match("3", "4"))

    def test_grade(self):
        good = grading.grade("answer \\boxed{42}", "42")
        self.assertTrue(good["correct"])
        self.assertEqual(good["match"], "exact")
        bad = grading.grade("answer \\boxed{41}", "42")
        self.assertFalse(bad["correct"])
        missing = grading.grade("answer 42", "42")
        self.assertFalse(missing["correct"])
        self.assertEqual(missing["issue"], "missing_complete_box")


if __name__ == "__main__":
    unittest.main()

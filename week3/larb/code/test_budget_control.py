import unittest
from budget_control import BudgetState


class BudgetTests(unittest.TestCase):
    def state(self):
        return BudgetState(budget=3, answer_cap=2, close_id=9, open_id=8)

    def test_budget_closes_thinking_without_ending_answer(self):
        s = self.state()
        for t in [8, 1, 2]:
            self.assertFalse(s.should_force)
            self.assertFalse(s.observe(t))
        self.assertTrue(s.should_force)
        self.assertFalse(s.observe(9))
        self.assertEqual(s.close_index, 3)
        self.assertFalse(s.should_force)
        self.assertFalse(s.observe(4))
        self.assertTrue(s.observe(5))
        self.assertEqual(s.answer_tokens, 2)

    def test_natural_close_does_not_force_a_second_close(self):
        s = self.state()
        for t in [8, 9, 4]:
            self.assertFalse(s.observe(t))
        self.assertFalse(s.should_force)
        self.assertTrue(s.observe(5))
        self.assertEqual(s.close_index, 1)

    def test_reopened_thinking_is_detected(self):
        s = self.state()
        for t in [8, 9, 8]:
            s.observe(t)
        self.assertTrue(s.reopened)

    def test_requests_have_independent_budgets(self):
        first, second = self.state(), self.state()
        for t in [8, 1, 2]:
            first.observe(t)
        self.assertTrue(first.should_force)
        self.assertFalse(second.should_force)
        self.assertEqual(second.count, 0)

    def test_nonthinking_response_uses_answer_allowance(self):
        s = BudgetState(budget=3, answer_cap=2, close_id=9, open_id=8, close_index=-1)
        self.assertFalse(s.should_force)
        self.assertFalse(s.observe(4))
        self.assertEqual(s.answer_tokens, 1)
        self.assertTrue(s.observe(5))
        self.assertEqual(s.answer_tokens, 2)


if __name__ == '__main__':
    unittest.main()

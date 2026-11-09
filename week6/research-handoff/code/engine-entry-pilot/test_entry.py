import unittest

from control import RequestControl
from evaluate import decide
from queue_policy import apply_pressure, entry_budget


class EntryTests(unittest.TestCase):
    def test_pressure_changes_budget_only_at_entry(self):
        self.assertEqual(entry_budget(8192, 1, 0), 4096)
        self.assertEqual(entry_budget(4096, 0, 0), 4096)
        state = RequestControl("probe--r00", [1] * 100, entry_budget(8192, 0, 0), [7, 9], 9, 0)
        self.assertFalse(apply_pressure(state, "entry", 1))
        self.assertEqual(state.budget, 8192)
        with self.assertRaises(ValueError):
            entry_budget(8192, 1, 1)

    def test_h1_exact_half_and_inconclusive_precedence(self):
        def metrics(tokens, good, correct):
            return dict(total_output_tokens=tokens, correct_on_time=good, correct=correct)

        block = dict(arrival=metrics(101, 4, 6), entry=metrics(95, 4, 6),
                     live=metrics(89, 4, 5))
        self.assertEqual(decide([block, block], [True])[0], "support")
        worse = dict(block, entry=metrics(96, 4, 6))
        self.assertEqual(decide([block, worse], [True])[0], "reject")
        quality_loss = dict(block, entry=metrics(95, 4, 5))
        self.assertEqual(decide([block, quality_loss], [True])[0], "reject")
        self.assertEqual(decide([block, block], [])[0], "inconclusive")
        no_saving = dict(block, live=metrics(101, 4, 5))
        self.assertEqual(decide([worse, no_saving], [True])[0], "inconclusive")

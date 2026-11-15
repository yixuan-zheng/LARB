import unittest

from larb_scaled.contract import RequestControl
from larb_scaled.policy import (PressureTracker, admission_budget, apply_cut, choose_victim,
                                eligible, pressure_threshold)


def state(progress, budget=8192, key="q"):
    control = RequestControl(key, [1] * progress, budget, [7, 9, 6], 9, 0, answer_cap=8)
    control.arrival_ts = 100.0
    return control


class PolicyTests(unittest.TestCase):
    def test_threshold_rounding(self):
        self.assertEqual(pressure_threshold(32), 8)
        self.assertEqual(pressure_threshold(16), 4)
        self.assertEqual(pressure_threshold(8), 4)
        self.assertEqual(pressure_threshold(4), 4)
        self.assertEqual(pressure_threshold(48), 12)

    def test_persistence(self):
        tracker = PressureTracker(8, persistence_steps=2)
        self.assertFalse(tracker.update(8))
        self.assertTrue(tracker.update(8))
        self.assertFalse(tracker.update(7))
        self.assertFalse(tracker.update(8))
        self.assertTrue(tracker.update(9))

    def test_admission_budget(self):
        self.assertEqual(admission_budget("fixed4k", 0, 8), 4096)
        self.assertEqual(admission_budget("fixed6k", 0, 8), 6096)
        self.assertEqual(admission_budget("fixed8k", 8, 8), 8192)
        self.assertEqual(admission_budget("arrival", 7, 8), 8192)
        self.assertEqual(admission_budget("arrival", 8, 8), 4096)
        self.assertEqual(admission_budget("live", 8, 8), 4096)
        with self.assertRaises(ValueError):
            admission_budget("typo", 0, 8)

    def test_eligibility_window(self):
        self.assertFalse(eligible(state(511)))
        self.assertTrue(eligible(state(512)))
        self.assertFalse(eligible(state(512, budget=4096)))
        self.assertFalse(eligible(state(7200)))
        closed = state(1000)
        closed.output.append(9)
        self.assertFalse(eligible(closed))

    def test_choose_largest_remaining_then_earliest(self):
        a = state(1000, key="a")
        b = state(600, key="b")
        c = state(1000, key="c")
        c.arrival_ts = 50.0
        self.assertEqual(choose_victim([a, b, c]).key, "b")
        b.budget = 4096
        self.assertEqual(choose_victim([a, b, c]).key, "c")
        self.assertIsNone(choose_victim([state(100)]))

    def test_apply_cut_is_downward_only(self):
        item = state(1000)
        self.assertTrue(apply_cut(item))
        self.assertEqual(item.budget, 4096)
        self.assertFalse(apply_cut(item))
        self.assertEqual(item.budget, 4096)


if __name__ == "__main__":
    unittest.main()

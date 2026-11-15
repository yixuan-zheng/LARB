import unittest

from larb_scaled.contract import Contract, RequestControl, move_rows


def legacy_contract():
    return Contract("legacy", [7, 9, 6], 9, 0, answer_cap=8)


def short_contract():
    return Contract("short_boxed", [10, 11, 12], 11, 0, answer_cap=3,
                    closing_brace_id=13, force_closing_brace=True)


class ContractTests(unittest.TestCase):
    def state(self, output=None, budget=8192, contract=None):
        return RequestControl.from_contract("p--a--signal--q--1", output or [],
                                            budget, contract or legacy_contract())

    def test_below_budget_does_not_cue(self):
        state = self.state([1] * 100)
        self.assertIsNone(state.next_forced())
        self.assertEqual(state.budget, 8192)

    def test_cut_above_target_cues_without_rewind(self):
        state = self.state([1] * 5000)
        before = list(state.output)
        self.assertTrue(state.change(4096, 1))
        self.assertEqual(state.next_forced(), 7)
        self.assertEqual(state.force_start, 5000)
        self.assertEqual(state.output, before)
        self.assertEqual(state.cut_history[0]["tokens"], 5000)

    def test_cut_below_target_waits_until_target(self):
        state = self.state([1] * 2000)
        self.assertTrue(state.change(4096, 1))
        self.assertIsNone(state.next_forced())
        state.output.extend([1] * 2096)
        self.assertEqual(state.next_forced(), 7)
        self.assertEqual(state.force_start, 4096)

    def test_natural_close_is_never_cut(self):
        state = self.state([1] * 100 + [9, 2, 3])
        self.assertFalse(state.change(4096, 1))
        self.assertTrue(state.ignored_after_close)
        self.assertIsNone(state.next_forced())

    def test_cue_and_cap_preserved(self):
        state = self.state([1] * 5000)
        state.change(4096, 1)
        for expected in state.cue:
            self.assertEqual(state.next_forced(), expected)
            state.output.append(expected)
        self.assertFalse(state.change(4096, 2))
        while len(state.output) - state.close_index - 1 < 8:
            state.output.append(2)
        self.assertEqual(state.next_forced(), 0)

    def test_one_way_no_raise(self):
        state = self.state([1] * 1000)
        self.assertTrue(state.change(4096, 1))
        self.assertFalse(state.change(8192, 2))
        self.assertFalse(state.change(4096, 3))
        self.assertEqual(state.budget, 4096)

    def test_short_contract_forces_closing_brace_then_eos(self):
        state = self.state([1] * 100, contract=short_contract())
        state.output.extend([10, 11, 12])
        state.force_start = 100
        # The cue's closing token already counts as one answer token.
        state.output.extend([2, 2])
        self.assertEqual(state.next_forced(), 13)
        state.output.append(13)
        self.assertEqual(state.next_forced(), 0)

    def test_short_contract_natural_brace_ends(self):
        state = self.state([1] * 100, contract=short_contract())
        state.output.extend([10, 11, 12, 2, 13])
        state.force_start = 100
        self.assertEqual(state.next_forced(), 0)

    def test_row_moves_follow_request(self):
        a = self.state([1] * 5000)
        b = self.state([1] * 100)
        b.key = "p--a--signal--q2--2"
        rows = {0: a, 1: b}
        move_rows(rows, [(0, 1, True)])
        self.assertIs(rows[1], a)
        self.assertIs(rows[0], b)
        self.assertTrue(rows[1].change(4096, 1))
        self.assertEqual(rows[1].next_forced(), 7)
        del rows[1]
        self.assertIs(rows[0], b)

    def test_contract_validation(self):
        with self.assertRaises(ValueError):
            Contract("bad", [1, 2], 9, 0, 10).validate()
        with self.assertRaises(ValueError):
            Contract("bad", [1, 9], 9, 0, 10, force_closing_brace=True).validate()


if __name__ == "__main__":
    unittest.main()

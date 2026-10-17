import unittest
from control import RequestControl, move_rows


class ControlTests(unittest.TestCase):
    def state(self, key='a'):
        return RequestControl(key, [], 100, [7, 9, 6], 9, 0, answer_cap=2)

    def test_update_after_generation_and_complete_cue(self):
        state = self.state()
        state.output.extend([1] * 5)
        self.assertTrue(state.change(3, 1))
        for token in [7, 9, 6]:
            self.assertEqual(state.next_forced(), token)
            state.output.append(token)
        self.assertIsNone(state.next_forced())
        state.output.append(4)
        self.assertEqual(state.next_forced(), 0)

    def test_natural_close_and_stale_command(self):
        state = self.state()
        state.output.extend([1, 9, 2])
        self.assertFalse(state.change(1, 1))
        self.assertIsNone(state.next_forced())
        self.assertFalse(state.change(1, 1))

    def test_moves_keep_identity_and_output_reference(self):
        a, b, c = self.state('a'), self.state('b'), self.state('c')
        rows = {0: a, 1: b, 3: c}
        move_rows(rows, [(3, 2, False), (0, 1, True)])
        self.assertIs(rows[1], a)
        self.assertIs(rows[0], b)
        self.assertIs(rows[2], c)
        a.change(1, 1)
        self.assertEqual(b.budget, 100)


if __name__ == '__main__':
    unittest.main()

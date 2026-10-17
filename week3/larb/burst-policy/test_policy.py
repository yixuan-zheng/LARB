import unittest
from policy import RequestControl, arrival_budget, apply_pressure, forced_token


class PolicyTests(unittest.TestCase):
    def state(self):
        return RequestControl('live-0', [], 16384, [7,9,6],9,0)

    def test_arrival_pressure_threshold_and_full_exemption(self):
        self.assertEqual(arrival_budget('full',9),16384)
        self.assertEqual(arrival_budget('arrival',1),16384)
        self.assertEqual(arrival_budget('arrival',2),2048)

    def test_only_live_policy_changes_running_budget(self):
        state=self.state();state.output.extend([1]*3000)
        self.assertFalse(apply_pressure(state,'arrival',2))
        self.assertTrue(apply_pressure(state,'live',2))
        self.assertEqual(forced_token(state),(7,None))
        state.output.append(7)
        self.assertFalse(apply_pressure(state,'live',2))

    def test_full_safety_cap_stops_without_cue(self):
        state=self.state();state.output.extend([1]*16384)
        self.assertEqual(forced_token(state),(0,'thinking_cap'))
        self.assertIsNone(state.force_start)

    def test_closed_answer_is_not_cut_again(self):
        state=self.state();state.output.extend([1,9,2])
        self.assertFalse(apply_pressure(state,'live',9))
        self.assertEqual(forced_token(state),(None,None))


if __name__=='__main__':
    unittest.main()

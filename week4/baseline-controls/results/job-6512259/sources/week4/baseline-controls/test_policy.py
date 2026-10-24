"""Mechanical regressions without model weights, vLLM, CUDA, or PACE."""
import copy
import unittest
from types import SimpleNamespace

from w4_policy import (LONG, SHORT, MODES, arrival_decision, attach_admission,
                       make_control, reduce_live, forced_token, move_rows)


def data(mode='live', key=None):
    return dict(key=key or mode+'-00', policy=mode, budget=LONG,
                cue=[7, 9, 6], close_id=9, eos_id=0, answer_cap=3)


def snapshot(phase='live', count=2, step=5):
    return dict(step=step, monotonic=10.0, active=[phase+'-00'],
                waiting=[phase+f'-{i+10:02d}' for i in range(count)])


class PolicyTests(unittest.TestCase):
    def state(self, mode='live', count=0):
        d = data(mode)
        attach_admission(d, snapshot(mode, count))
        return make_control(d, [])

    def test_admission_and_live_same_rule_at_threshold(self):
        for count in [0, 1, 2, 3]:
            budgets = []
            for mode in ['admission', 'live']:
                d = data(mode)
                attach_admission(d, snapshot(mode, count))
                budgets.append(d['budget'])
            self.assertEqual(budgets, [SHORT if count >= 2 else LONG]*2)

    def test_arrival_only_decides_on_arrival(self):
        for mode in ('full', 'arrival', 'admission', 'live'):
            decision = arrival_decision(mode, snapshot(mode), mode, 10.1, 2)
            self.assertEqual(decision['budget'], SHORT if mode == 'arrival' else LONG)

    def test_arrival_stale_missing_and_future_snapshot_fall_back(self):
        for observed in [None, snapshot(), dict(snapshot(), monotonic=20)]:
            result = arrival_decision('arrival', observed, 'live', 15, 2)
            self.assertEqual(result['budget'], LONG)
            self.assertTrue(result['fallback'])

    def test_other_phase_does_not_supply_pressure(self):
        d = data()
        attach_admission(d, snapshot('other', 9))
        self.assertEqual(d['budget'], LONG)

    def test_full_and_arrival_retain_initial_decision_at_admission(self):
        for mode, budget in [('full', LONG), ('arrival', LONG), ('arrival', SHORT)]:
            d = dict(data(mode), budget=budget)
            attach_admission(d, snapshot(mode, 5))
            self.assertEqual(d['budget'], budget)

    def test_new_requests_share_one_post_schedule_snapshot(self):
        snap = snapshot(count=3)
        params = [SimpleNamespace(extra_args={'burst': data(key=f'live-{i:02d}')})
                  for i in range(2)]
        for p in params:
            attach_admission(p.extra_args['burst'], snap)
        self.assertEqual(params[0].extra_args['burst']['admission'],
                         params[1].extra_args['burst']['admission'])

    def test_repeat_admission_does_not_reset_choice(self):
        d = data()
        attach_admission(d, snapshot(count=0))
        original = copy.deepcopy(d)
        self.assertFalse(attach_admission(d, snapshot(count=9, step=6)))
        self.assertEqual(d, original)

    def test_worker_rejects_missing_scheduler_metadata(self):
        with self.assertRaises(RuntimeError):
            make_control(data(), [])

    def test_live_does_not_revise_at_zero_generation(self):
        self.assertFalse(reduce_live(self.state(), 'live', 9))

    def test_admission_never_changes_during_generation(self):
        for mode in ['full', 'arrival', 'admission']:
            state = self.state(mode)
            state.output.extend([1]*3000)
            self.assertFalse(reduce_live(state, mode, 9))
            self.assertEqual(state.budget, LONG)

    def test_live_reduces_once_and_starts_cue_next_sample(self):
        state = self.state()
        state.output.extend([1]*3000)
        self.assertTrue(reduce_live(state, 'live', 2))
        self.assertEqual(state.budget, SHORT)
        self.assertFalse(reduce_live(state, 'live', 9))
        self.assertEqual(forced_token(state), (7, None))

    def test_pressure_below_threshold_does_not_reduce(self):
        state = self.state()
        state.output.append(1)
        self.assertFalse(reduce_live(state, 'live', 1))

    def test_complete_cue_before_answer_and_shared_answer_cap(self):
        state = self.state(count=2)
        state.output.extend([1]*SHORT)
        for token in [7, 9, 6]:
            self.assertEqual(forced_token(state), (token, None))
            state.output.append(token)
        self.assertEqual(forced_token(state), (None, None))
        state.output.extend([3, 4])
        self.assertEqual(forced_token(state), (0, 'answer_cap'))

    def test_natural_close_blocks_late_reduction(self):
        state = self.state()
        state.output.extend([1, 9, 2])
        self.assertFalse(reduce_live(state, 'live', 9))
        self.assertEqual(forced_token(state), (None, None))

    def test_full_safety_cap_is_failure_without_cue(self):
        state = self.state('full')
        state.output.extend([1]*LONG)
        self.assertEqual(forced_token(state), (0, 'thinking_cap'))
        self.assertIsNone(state.force_start)

    def test_row_moves_retain_request_and_output_identity(self):
        a, b, c = self.state(), self.state('admission'), self.state('full')
        rows = {0:a, 1:b, 3:c}
        original = a.output
        move_rows(rows, [(3, 2, False), (0, 1, True)])
        rows[1].output.append(1)
        self.assertTrue(reduce_live(rows[1], 'live', 2))
        self.assertIs(rows[1], a)
        self.assertIs(rows[1].output, original)
        self.assertEqual(rows[0].budget, LONG)
        self.assertIs(rows[2], c)


if __name__ == '__main__':
    unittest.main()

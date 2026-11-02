"""Mechanical regressions without model weights, vLLM, CUDA, or PACE."""
import copy
import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from w5_policy import (FIXED, LIVE_MODES, LONG, MEASURED, MODES, SHORT, TRIGGERS,
                       arrival_decision, attach_admission, forced_token, make_control,
                       move_rows, pressure_budget, reduce_live, trigger_threshold)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def data(mode='live', key=None):
    return dict(key=key or mode + '-00', policy=mode, budget=LONG,
                cue=[7, 9, 6], close_id=9, eos_id=0, answer_cap=3)


def snapshot(phase='live', count=2, step=5):
    return dict(step=step, monotonic=10.0, active=[phase + '-00'],
                waiting=[phase + f'-{i + 10:02d}' for i in range(count)])


class Base(unittest.TestCase):
    def state(self, mode='live', count=0):
        d = data(mode)
        attach_admission(d, snapshot(mode, count))
        return make_control(d, [])


class ThresholdTests(Base):
    def test_both_triggers_are_selectable_and_differ_at_one_waiter(self):
        self.assertEqual(TRIGGERS, {'live': 2, 'live_one': 1})
        self.assertEqual([trigger_threshold(m) for m in ('live', 'live_one')], [2, 1])
        self.assertEqual([pressure_budget('live', w) for w in (0, 1, 2)], [LONG, LONG, SHORT])
        self.assertEqual([pressure_budget('live_one', w) for w in (0, 1, 2)], [LONG, SHORT, SHORT])
        self.assertIsNone(trigger_threshold('fixed2048'))
        self.assertEqual(set(MEASURED), {'fixed2048', 'fixed4096', 'live', 'live_one'})
        self.assertTrue(set(MEASURED) <= set(MODES))

    def test_fixed_policies_never_change_budget_while_thinking(self):
        for mode, budget in FIXED.items():
            state = self.state(mode)
            state.output.extend([1] * 3000)
            self.assertFalse(reduce_live(state, mode, 9))
            self.assertEqual(state.budget, budget)

    def test_calibration_policy_never_reacts_to_load(self):
        for count in (0, 1, 5):
            d = data('full')
            attach_admission(d, snapshot('full', count))
            self.assertEqual(d['budget'], LONG)
            self.assertIsNone(d['admission']['trigger'])
        state = self.state('full')
        state.output.append(1)
        self.assertFalse(reduce_live(state, 'full', 9))


class AdmissionTests(Base):
    def test_admission_thresholds_match_each_policy(self):
        for count in (0, 1, 2, 3):
            for mode in LIVE_MODES:
                d = data(mode)
                attach_admission(d, snapshot(mode, count))
                self.assertEqual(d['budget'], SHORT if count >= TRIGGERS[mode] else LONG)

    def test_decision_is_recorded_once_and_before_generation(self):
        d = data('live_one')
        self.assertTrue(attach_admission(d, snapshot('live_one', 1)))
        self.assertEqual(d['admission']['trigger'], 1)
        original = copy.deepcopy(d)
        self.assertFalse(attach_admission(d, snapshot('live_one', 9, step=6)))
        self.assertEqual(d, original)
        with self.assertRaises(RuntimeError):
            make_control(data('live_one'), [])

    def test_other_phase_and_stale_snapshot_do_not_supply_pressure(self):
        d = data('live_one')
        attach_admission(d, snapshot('other', 9))
        self.assertEqual(d['budget'], LONG)
        decision = arrival_decision('live_one', None, 'live_one', 15, 2)
        self.assertEqual(decision['budget'], LONG)
        self.assertTrue(decision['fallback'])
        self.assertEqual(decision['trigger'], 1)

    def test_new_requests_share_one_post_schedule_snapshot(self):
        snap = snapshot('live_one', 3)
        params = [SimpleNamespace(extra_args={'burst': data('live_one', f'live_one-{i:02d}')})
                  for i in range(2)]
        for p in params:
            attach_admission(p.extra_args['burst'], snap)
        self.assertEqual(params[0].extra_args['burst']['admission'],
                         params[1].extra_args['burst']['admission'])
class LiveCutTests(Base):
    def test_one_waiter_binds_where_two_waiters_does_not(self):
        for mode, count, expected in [('live', 1, False), ('live_one', 1, True),
                                      ('live', 2, True), ('live_one', 2, True)]:
            state = self.state(mode)
            state.output.extend([1] * 500)
            self.assertEqual(reduce_live(state, mode, count), expected,
                             f'{mode} with {count} waiting')
            self.assertEqual(state.budget, SHORT if expected else LONG)

    def test_reduction_is_single_and_irreversible(self):
        state = self.state('live_one')
        state.output.extend([1] * 3000)
        self.assertTrue(reduce_live(state, 'live_one', 1))
        self.assertEqual(state.version, 1)
        self.assertFalse(reduce_live(state, 'live_one', 3))

    def test_zero_generation_and_natural_close_block_reduction(self):
        state = self.state('live_one')
        self.assertFalse(reduce_live(state, 'live_one', 9))
        state.output.extend([1, 9, 2])
        self.assertFalse(reduce_live(state, 'live_one', 9))
        self.assertIsNone(state.force_start)

    def test_cue_runs_to_completion_then_answer_cap_applies(self):
        state = self.state('live_one', count=1)
        state.output.extend([1] * SHORT)
        for token in [7, 9, 6]:
            self.assertEqual(forced_token(state), (token, None))
            state.output.append(token)
        self.assertEqual(forced_token(state), (None, None))
        state.output.extend([3, 4])
        self.assertEqual(forced_token(state), (0, 'answer_cap'))

    def test_row_moves_retain_state_and_identity(self):
        a, b, c = self.state('live_one'), self.state('live'), self.state('full')
        rows = {0: a, 1: b, 3: c}
        original = a.output
        move_rows(rows, [(3, 2, False), (0, 1, True)])
        rows[1].output.extend([1] * 600)
        self.assertTrue(reduce_live(rows[1], 'live_one', 1))
        self.assertIs(rows[1], a)
        self.assertIs(rows[1].output, original)
        self.assertEqual(rows[0].budget, LONG)


class UnchangedControllerTests(unittest.TestCase):
    def test_week3_and_week4_controller_sources_are_byte_identical(self):
        lock = json.loads((HERE / 'source-lock.json').read_text())
        self.assertIn('week4/baseline-controls/w4_policy.py', lock)
        self.assertIn('week3/larb/burst-policy/adapter.py', lock)
        self.assertIn('week3/larb/serving-proof/control.py', lock)
        for name, expected in lock.items():
            self.assertEqual(hashlib.sha256((REPO / name).read_bytes()).hexdigest(),
                             expected, name)


if __name__ == '__main__':
    unittest.main()

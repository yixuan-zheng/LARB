import math
import unittest
from reference import Parameters, Load, budget, confidence, Request, Costs


class PolicyTests(unittest.TestCase):
    def test_budget_paper_endpoints_and_clips(self):
        self.assertEqual([budget(n, 1) for n in [0, 50, 275, 1000]], [6, 6, 15, 15])
        self.assertEqual(budget(50, 100), 2)
        self.assertEqual(budget(275, 20), 7)

    def test_load_ema_initialization_and_target(self):
        load = Load(); self.assertEqual(load.ema, 0)
        self.assertEqual(load.observe_atp(2), .97)
        self.assertAlmostEqual(load.ema, .6)
        at_target = Load(ema=10)
        self.assertEqual(at_target.observe_atp(10), .95)

    def test_two_slot_default_saturates(self):
        for active in [0, 1, 2]:
            load = Load()
            for _ in range(100): self.assertEqual(load.observe_atp(active), .97)
            self.assertEqual(budget(150, active), budget(150, 0))

    def test_explicit_capacity_adaptation(self):
        load = Load(Parameters(target=1), ema=2)
        self.assertLess(load.observe_atp(2), .95)
        self.assertEqual(budget(275, 2, load.params), 7)

    def test_invalid_parameters_and_load(self):
        for args in [dict(target=0), dict(alpha=0), dict(base=float('nan')), dict(min_chunks=1)]:
            with self.assertRaises(ValueError): Parameters(**args)
        with self.assertRaises(ValueError): Load().observe_atp(float('nan'))


class ConfidenceTests(unittest.TestCase):
    def score(self, rows, **kwargs):
        return confidence(rows, complete=True, nonempty_answer=True, **kwargs)

    def test_geometric_not_arithmetic(self):
        self.assertAlmostEqual(self.score([[(1, math.log(.5))], [(1, math.log(.98))]]), .7)

    def test_top_one_not_insertion_or_sampled(self):
        self.assertAlmostEqual(self.score([[(4, math.log(.01)), (1, math.log(.98))]]), .98)

    def test_empty_missing_and_bad_probabilities(self):
        for rows in [[], [[]], [[(2, -.1)]], [[(1, .1)]], [[(1, float('nan'))]], [[(1, float('-inf'))]]]:
            self.assertIsNone(self.score(rows))

    def test_capped_or_empty_answer_never_exits(self):
        for complete, nonempty in [(False, True), (True, False)]:
            self.assertIsNone(confidence([[(1, 0.)]], complete=complete, nonempty_answer=nonempty))

    def test_long_window_stable_in_log_space(self):
        self.assertAlmostEqual(self.score([[(1, math.log(.96))]] * 10000), .96)


class LifecycleTests(unittest.TestCase):
    def make_probe(self, phase='b0', key='q0'):
        r = Request(phase, key, 2)
        probe = r.checkpoint([1, 2], atp=True)
        return r, probe

    def test_reject_restores_exact_prefix(self):
        r, p = self.make_probe(); prefix = r.prefix
        self.assertEqual(r.accept_probe(p, prefix, .9, .95), 'thinking')
        self.assertEqual(r.prefix, prefix)
        with self.assertRaises(ValueError): r.checkpoint([1, 9])

    def test_threshold_equality_continues(self):
        r, p = self.make_probe()
        self.assertEqual(r.accept_probe(p, r.prefix, .95, .95), 'thinking')

    def test_accept_requires_complete_transition_and_final(self):
        r, p = self.make_probe();r.accept_probe(p, r.prefix, .98, .95)
        with self.assertRaises(RuntimeError): r.finish(eos=True, within_answer_cap=True)
        r.close_completed();r.finish(eos=True, within_answer_cap=True)
        self.assertEqual(r.state, 'complete')

    def test_final_chunk_probe_counted_then_forces(self):
        r, p = self.make_probe();r.accept_probe(p, r.prefix, None, .95)
        p = r.checkpoint([1, 2, 3], atp=True)
        self.assertIsNotNone(p)
        self.assertEqual(r.accept_probe(p, r.prefix, None, .95), 'closing')

    def test_token_cap_before_probe(self):
        r = Request('b0', 'q0', 10, token_cap=2)
        self.assertIsNone(r.checkpoint([1, 2], atp=True))
        self.assertEqual(r.state, 'closing')
        with self.assertRaises(RuntimeError): r.checkpoint([1, 2, 3])

    def test_natural_close_and_answer_cap(self):
        r = Request('b0', 'q0', 2);r.checkpoint([1], natural_close=True)
        with self.assertRaises(RuntimeError): r.checkpoint([1, 2], atp=True)
        r.finish(eos=False, within_answer_cap=False)
        self.assertEqual(r.state, 'failed')

    def test_foreign_stale_and_phase_isolation(self):
        r, p = self.make_probe();other, foreign = self.make_probe('b1')
        self.assertNotEqual(p, foreign)
        with self.assertRaises(ValueError): r.accept_probe(foreign, r.prefix, .99, .95)
        with self.assertRaises(ValueError): r.accept_probe(p, [9], .99, .95)
        r.accept_probe(p, r.prefix, .2, .95)
        with self.assertRaises(ValueError): r.accept_probe(p, r.prefix, .99, .95)

    def test_cancel_discards_late_probe(self):
        r, p = self.make_probe();r.cancel()
        with self.assertRaises(ValueError): r.accept_probe(p, r.prefix, .99, .95)

    def test_no_duplicate_atp_without_progress(self):
        r, p = self.make_probe();r.accept_probe(p, r.prefix, .2, .95)
        self.assertIsNone(r.checkpoint(r.prefix, atp=True))
        self.assertEqual(r.count, 1)


class CostTests(unittest.TestCase):
    def test_replay_probe_and_discard_are_charged(self):
        costs = Costs()
        for i, kind in enumerate(['reason', 'probe', 'reason', 'final']):
            costs.record(str(i), kind=kind, prompt_tokens=1000, computed_prefill_tokens=1000,
                         cached_tokens=0, decoded_tokens=20, discarded_tokens=10 if kind == 'probe' else 0,
                         start=float(i), end=i + 1.)
        self.assertEqual(costs.totals()['computed_prefill_tokens'], 4000)
        self.assertEqual(costs.totals()['decoded_tokens'], 80)
        self.assertEqual(costs.totals()['discarded_tokens'], 10)

    def test_missing_counters_and_duplicates_rejected(self):
        costs = Costs();args = dict(kind='probe', prompt_tokens=10, computed_prefill_tokens=10,
            cached_tokens=0, decoded_tokens=2, discarded_tokens=2, start=0., end=1.)
        costs.record('p', **args)
        with self.assertRaises(ValueError): costs.record('p', **args)
        with self.assertRaises(ValueError): costs.record('q', **dict(args, computed_prefill_tokens=None))


if __name__ == '__main__': unittest.main()

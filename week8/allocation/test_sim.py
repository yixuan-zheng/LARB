import copy
import unittest

import sim
from sim import arrival_rule, fixed, rate, simulate, summarize, value_rule

# a flat 100 tokens/s and a 400-token checkpoint keep the arithmetic by hand:
# checkpoint at 4 s, then 1 s to answer (100 tokens) or 6 s to think on (600)
FLAT = {1: 100.0}


def req(key, arrival=0.0, value=0.0, deadline=240.0, short=(100, 0), long=(600, 1)):
    return dict(key=key, prefix=key, arrival=arrival, deadline=deadline, checkpoint=400,
                short=short, long=long, value=value)


def by_key(results):
    return {r['key']: r for r in results}


class Rate(unittest.TestCase):
    def test_measured_points_and_interpolation(self):
        self.assertAlmostEqual(rate(1), 76.7)
        self.assertAlmostEqual(rate(32), 54.7)
        self.assertAlmostEqual(rate(20), (65.8 + 61.3) / 2)
        self.assertAlmostEqual(rate(40), 54.7)  # flat past the last point
        self.assertAlmostEqual(rate(32, speed=1.25), 54.7 * 1.25)


class Replay(unittest.TestCase):
    def setUp(self):
        self.saved, sim.RATE = sim.RATE, FLAT

    def tearDown(self):
        sim.RATE = self.saved

    def test_short_and_long_service(self):
        short = simulate([req('a')], fixed('short'), slots=1)[0]
        long = simulate([req('a')], fixed('long'), slots=1)[0]
        self.assertAlmostEqual(short['finish'], 5.0)
        self.assertAlmostEqual(long['finish'], 10.0)
        self.assertEqual((short['correct'], long['correct']), (0, 1))
        self.assertEqual((short['tokens'], long['tokens']), (500, 1000))

    def test_correct_but_late_is_not_good(self):
        r = simulate([req('a', deadline=8.0)], fixed('long'), slots=1)[0]
        self.assertEqual((r['correct'], r['on_time'], r['good']), (1, 0, 0))

    def test_fifo_waits_for_a_free_slot(self):
        out = by_key(simulate([req('a'), req('b', arrival=0.5)], fixed('short'), slots=1))
        # b arrives at 0.5, a frees the slot at 5.0, b answers at 10.0
        self.assertEqual(out['b']['start'], 5.0)
        self.assertAlmostEqual(out['b']['finish'], 10.0)
        self.assertAlmostEqual(out['b']['latency'], 9.5)

    def test_value_rule_prices_the_queue(self):
        # a reaches its checkpoint with b waiting: price = 0.5 * 1 waiter / 1 slot
        for value, arm in [(0.6, 'long'), (0.4, 'short')]:
            policy = value_rule('v', lambda r: r['value'], lam=0.5, slots=1)
            out = by_key(simulate([req('a', value=value), req('b', arrival=1.0)], policy, slots=1))
            self.assertEqual(out['a']['arm'], arm)
            self.assertEqual(out['a']['waiting_seen'], 1)

    def test_value_rule_idle_server(self):
        # nobody waiting: any positive value extends, zero value never does
        policy = value_rule('v', lambda r: r['value'], lam=0.5, slots=1)
        self.assertEqual(simulate([req('a', value=0.01)], policy, slots=1)[0]['arm'], 'long')
        self.assertEqual(simulate([req('a', value=0.0)], policy, slots=1)[0]['arm'], 'short')

    def test_arrival_rule_counts_waiters_at_the_door(self):
        out = by_key(simulate([req('a'), req('b'), req('c')], arrival_rule(threshold=1), slots=1))
        # a is admitted at once and b sees an empty queue; c sees b waiting
        self.assertEqual([out[k]['arm'] for k in 'abc'], ['long', 'long', 'short'])
        self.assertEqual([out[k]['waiting_seen'] for k in 'abc'], [0, 0, 1])

    def test_lag_sees_an_older_queue(self):
        # b arrives at 3, a hits its checkpoint in the step from 3 to 4
        policy = value_rule('v', lambda r: r['value'], lam=0.5, slots=1)
        requests = [req('a', value=0.4), req('b', arrival=3.0)]
        self.assertEqual(by_key(simulate(requests, policy, slots=1))['a']['arm'], 'short')
        self.assertEqual(by_key(simulate(requests, policy, slots=1, lag=3.0))['a']['arm'], 'long')

    def test_speed_scales_time(self):
        r = simulate([req('a')], fixed('long'), slots=1, speed=2.0)[0]
        self.assertAlmostEqual(r['finish'], 5.0)

    def test_two_slots_run_together(self):
        out = by_key(simulate([req('a'), req('b')], fixed('short'), slots=2))
        self.assertEqual((out['a']['start'], out['b']['start']), (0.0, 0.0))
        self.assertAlmostEqual(out['b']['finish'], 5.0)

    def test_filler_holds_a_slot_but_is_not_scored(self):
        filler = dict(key='f', arrival=0.0, deadline=240.0, checkpoint=None, tokens=300)
        results = simulate([filler, req('a', arrival=0.5)], fixed('long'), slots=1)
        out = by_key(results)
        self.assertEqual(out['a']['start'], 3.0)
        self.assertFalse(out['f']['scored'])
        s = summarize(results, minutes=1.0)
        self.assertEqual((s['requests'], s['good'], s['extended']), (1, 1, 1))
        self.assertAlmostEqual(s['goodput_per_min'], 1.0)

    def test_inputs_not_modified(self):
        requests = [req('a'), req('b', arrival=1.0)]
        before = copy.deepcopy(requests)
        simulate(requests, fixed('long'), slots=1)
        self.assertEqual(requests, before)


if __name__ == '__main__':
    unittest.main()

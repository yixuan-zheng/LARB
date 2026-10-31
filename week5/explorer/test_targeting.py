import copy
import unittest

from targeting import category, cut_all_decision, eligible, free_time, shadow_decision

# 50 tokens/s, 10 s to answer after the cue, 40 s per admitted waiter,
# and every request is assumed to have 4,000 tokens of thinking left
EST = dict(tau=0.02, answer=10.0, service=40.0, remaining=lambda _: 4000)
NOW = 100.0


def run(key, tokens, budget=16384, closed=False, cued=False):
    return dict(key=key, tokens=tokens, budget=budget, closed=closed, cued=cued)


def wait(key, slack):
    return dict(key=key, deadline=NOW + slack)


# a: early in its thinking (cut frees it in ~31 s), b: past 2,048 (cut frees it in 10 s);
# uncut, both hold their slot for 90 s
A, B = run('a', 1000), run('b', 3000)


class Targeting(unittest.TestCase):
    def test_free_times(self):
        self.assertAlmostEqual(free_time(A, EST), 90.0)
        self.assertAlmostEqual(free_time(A, EST, cut=True), 30.96)
        self.assertAlmostEqual(free_time(B, EST, cut=True), 10.0)
        self.assertAlmostEqual(free_time(run('c', 500, closed=True), EST), 10.0)

    def test_rescue_cuts_the_one_that_helps(self):
        # only cutting b gets the waiter in: 10 + 40 = 50 <= 60
        d = shadow_decision(NOW, [A, B], [wait('w', 60)], EST)
        self.assertEqual((d['cut'], d['reason']), ('b', 'rescue'))

    def test_tie_picks_soonest_free(self):
        # cutting either works (71 s or 50 s <= 80 s), so take b, which frees sooner
        d = shadow_decision(NOW, [A, B], [wait('w', 80)], EST)
        self.assertEqual(d['cut'], 'b')

    def test_doomed_waiter_no_cut(self):
        d = shadow_decision(NOW, [A, B], [wait('w', 30)], EST)
        self.assertEqual((d['cut'], d['reason']), (None, 'doomed'))

    def test_fine_anyway_no_cut(self):
        d = shadow_decision(NOW, [A, B], [wait('w', 200)], EST)
        self.assertEqual((d['cut'], d['reason']), (None, 'fine'))

    def test_never_more_than_one_cut(self):
        d = shadow_decision(NOW, [A, B], [wait('w1', 60), wait('w2', 60)], EST)
        self.assertIsInstance(d['cut'], str)

    def test_second_waiter_gets_second_slot(self):
        # b is already answering (frees in 10 s) and goes to w1; w2 waits for a
        cued = run('b', 2048, cued=True)
        waiters = [wait('w1', 1000), wait('w2', 100)]
        self.assertEqual(shadow_decision(NOW, [A, cued], waiters, EST)['cut'], 'a')
        # same queue, reversed deadlines: w1 is fine with b's slot, so nothing to do
        waiters = [wait('w1', 100), wait('w2', 1000)]
        self.assertEqual(shadow_decision(NOW, [A, cued], waiters, EST)['reason'], 'fine')

    def test_ineligible_never_cut(self):
        others = [run('c', 500, closed=True), run('d', 2048, cued=True),
                  run('e', 1500, budget=2048), run('f', 0)]
        for r in others:
            self.assertFalse(eligible(r))
        d = shadow_decision(NOW, others[:2], [wait('w', 5)], EST)
        self.assertEqual((d['cut'], d['reason']), (None, 'nothing_eligible'))
        self.assertEqual(cut_all_decision(others, [wait('w', 5)]), [])

    def test_no_waiter(self):
        self.assertEqual(shadow_decision(NOW, [A, B], [], EST)['reason'], 'no_waiter')

    def test_cut_all_baseline(self):
        self.assertEqual(cut_all_decision([A, B], [wait('w', 60)]), ['a', 'b'])
        self.assertEqual(cut_all_decision([A, B], []), [])
        # the week 4 live rule is the same thing at two waiters
        self.assertEqual(cut_all_decision([A, B], [wait('w', 60)], threshold=2), [])

    def test_categories(self):
        both = cut_all_decision([A, B], [wait('w', 60)])
        self.assertEqual(category(dict(cut='b', reason='rescue'), both), 'one_of_two')
        self.assertEqual(category(dict(cut=None, reason='doomed'), both), 'doomed')
        self.assertEqual(category(dict(cut=None, reason='fine'), both), 'fine')
        self.assertEqual(category(dict(cut='b', reason='rescue'), ['b']), 'agree')
        self.assertEqual(category(dict(cut=None, reason='no_waiter'), []), 'agree')

    def test_inputs_not_modified(self):
        running, waiters = [A, B], [wait('w', 60)]
        before = copy.deepcopy((running, waiters))
        shadow_decision(NOW, running, waiters, EST)
        cut_all_decision(running, waiters)
        self.assertEqual((running, waiters), before)


if __name__ == '__main__':
    unittest.main()

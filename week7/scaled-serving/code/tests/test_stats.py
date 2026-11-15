import unittest

from larb_scaled import stats


class StatsTests(unittest.TestCase):
    def test_wilson(self):
        low, high = stats.wilson_interval(40, 100)
        self.assertLess(low, 0.40)
        self.assertGreater(high, 0.40)
        self.assertEqual(stats.wilson_interval(0, 0), (None, None))

    def test_mde_and_required_pairs(self):
        mde = stats.paired_mde(628, 0.20)
        self.assertAlmostEqual(mde, 0.05, places=2)
        required = stats.required_pairs(0.05, 0.20)
        self.assertTrue(620 <= required <= 640)

    def test_effective_n(self):
        self.assertAlmostEqual(stats.effective_n(220, 4, 0.2), 550.0)
        self.assertAlmostEqual(stats.effective_n(220, 4, 0.4), 400.0)
        self.assertAlmostEqual(stats.effective_n(220, 4, 0.6), 314.2857, places=3)

    def test_bootstrap_and_sign(self):
        pairs = [(1, 0)] * 20 + [(0, 0)] * 30 + [(1, 1)] * 50
        result = stats.cluster_bootstrap(pairs, resamples=2000, seed=3)
        self.assertEqual(result["n"], 100)
        self.assertGreater(result["mean"], 0)
        self.assertLessEqual(result["ci_low"], result["mean"])
        self.assertGreaterEqual(result["ci_high"], result["mean"])
        sign = stats.sign_test([1] * 10 + [0] * 2)
        self.assertEqual(sign["positives"], 10)
        self.assertLess(sign["p"], 0.01)


if __name__ == "__main__":
    unittest.main()

import unittest

from policy import admission, coin_mode, shuffle_modes
from reference.routed_contract import choose


class PolicyTest(unittest.TestCase):
    def test_caps(self):
        for mode, cap in enumerate((0, 2048, 8192)):
            self.assertEqual(admission("task", True, cached_mode=mode), (mode, cap, False))
            self.assertEqual(admission("combined", True, cached_mode=mode), (mode, min(cap, 4096), True))
        self.assertEqual(admission("fixed4k", False), (2, 4096, False))
        self.assertEqual(admission("load", False), (2, 8192, True))

    def test_archived_policy_parity(self):
        for arm in ("fixed4k", "fixed8k", "task", "load", "combined", "shuffle-load"):
            for mode in range(3):
                for pressure in (False, True):
                    row = {"selected": mode, "shuffle_mode": mode}
                    self.assertEqual(admission(arm, pressure, cached_mode=mode),
                                     choose(arm, row, pressure))
        for request_id in ("repeat-request", "other-request"):
            for seed in (151, 411):
                for arm in ("coin", "coin-load"):
                    for pressure in (False, True):
                        # Samplers differ. The controller should match given the same action.
                        row = {f"coin_{seed}": coin_mode(request_id, seed)}
                        self.assertEqual(admission(arm, pressure, request_id=request_id, seed=seed),
                                         choose(f"{arm}-{seed}", row, pressure))

    def test_probability_and_retry(self):
        ids = [str(i) for i in range(1000)]
        draws = [coin_mode(key, 151) for key in ids]
        self.assertEqual(draws, [coin_mode(key, 151) for key in ids])
        self.assertTrue(350 <= draws.count(2) <= 450)
        for key, mode in zip(ids, draws):
            self.assertEqual(admission("coin-load", True, request_id=key),
                             (mode, 4096 if mode == 2 else 2048, True))

    def test_shuffle(self):
        routes = dict(a=1,b=2,c=1,d=1)
        sources = dict(a="x",b="x",c="y",d="y")
        shuffled = shuffle_modes(routes,sources,151)
        self.assertEqual(sorted(shuffled[k] for k in ("a","b")), [1,2])
        self.assertEqual([shuffled[k] for k in ("c","d")], [1,1])


if __name__ == "__main__":
    unittest.main()

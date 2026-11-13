import unittest

from larb_scaled import config
from larb_scaled.policy import pressure_threshold, validate_policy_config


class ConfigTests(unittest.TestCase):
    def test_protocol_validates(self):
        protocol, p1, p2 = config.validate_all()
        self.assertEqual(protocol["engine"]["max_num_seqs"], 32)
        self.assertEqual(protocol["budgets"]["long"], 8192)
        self.assertEqual(p1["gates"]["bridge"]["expected_responses"], 120)
        self.assertEqual(p2["arms"], ["fixed4k", "fixed8k", "arrival", "live"])

    def test_threshold_matches_grid(self):
        protocol = config.load_protocol()
        pressure = protocol["policy"]["pressure"]
        value = pressure_threshold(protocol["engine"]["max_num_seqs"],
                                   pressure["threshold_fraction"],
                                   pressure["threshold_minimum"])
        self.assertIn(value, pressure["threshold_grid"])

    def test_policy_config(self):
        config.validate_protocol(config.load_protocol())
        self.assertTrue(validate_policy_config(config.load_protocol()["policy"]))

    def test_config_hashes(self):
        hashes = config.config_hashes()
        self.assertIn("configs/protocol.json", hashes)
        self.assertEqual(len(hashes["configs/protocol.json"]), 64)


if __name__ == "__main__":
    unittest.main()

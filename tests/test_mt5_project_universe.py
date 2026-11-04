import unittest

from scripts.mt5_project_universe import project_assets


class TestProjectMarketUniverse(unittest.TestCase):
    def test_includes_policy_and_configured_experiment_assets(self):
        assets = project_assets()
        instruments = {asset["instrument"] for asset in assets}
        self.assertIn("EURUSD", instruments)
        self.assertIn("XAUUSD", instruments)
        self.assertIn("AAPL", instruments)
        self.assertIn("NVDA", instruments)
        self.assertGreaterEqual(len(instruments), 54)

    def test_broker_aliases_remain_explicit(self):
        by_instrument = {asset["instrument"]: asset for asset in project_assets()}
        self.assertEqual(by_instrument["NVDA"]["broker_symbol"], "NVIDIA")
        self.assertEqual(by_instrument["V"]["broker_symbol"], "VISA")


if __name__ == "__main__":
    unittest.main()

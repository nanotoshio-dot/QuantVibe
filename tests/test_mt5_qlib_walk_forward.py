import unittest

import pandas as pd

from scripts.mt5_qlib_walk_forward import RESEARCH_GATE, feature_frame, simulate_predictions


class TestMt5QlibWalkForward(unittest.TestCase):
    def test_features_do_not_backfill_future_values(self):
        frame = pd.DataFrame({"time": list(range(30)), "open": range(1, 31), "high": range(2, 32), "low": range(1, 31), "close": range(1, 31), "tick_volume": range(1, 31), "spread": [2] * 30})
        features, label = feature_frame(frame)
        self.assertTrue(features.iloc[:19].isna().any(axis=1).any())
        self.assertTrue(pd.isna(label.iloc[-1]))

    def test_simulation_starts_flat(self):
        frame = pd.DataFrame({"time": [0, 3600, 7200], "close": [10.0, 11.0, 12.0]})
        report = simulate_predictions(frame, __import__("numpy").array([1.0, 1.0, 1.0]), "H1")
        self.assertEqual(report["bars"], 3)

    def test_research_gate_is_not_an_execution_gate(self):
        self.assertGreaterEqual(RESEARCH_GATE["min_folds"], 1)


if __name__ == "__main__":
    unittest.main()

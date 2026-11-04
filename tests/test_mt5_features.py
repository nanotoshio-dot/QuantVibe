import unittest

import pandas as pd

from qlib_side.mt5_features import FEATURE_NAMES, calculate_features


def frame(times):
    size = len(times)
    return pd.DataFrame({"time": times, "open": range(10, 10 + size), "high": range(11, 11 + size), "low": range(9, 9 + size), "close": range(10, 10 + size), "tick_volume": range(100, 100 + size), "spread": [2] * size})


class TestMt5Features(unittest.TestCase):
    def test_schema_is_stable_and_causal_warmup_is_nan(self):
        features = calculate_features(frame([index * 3600 for index in range(50)]), "H1")
        self.assertEqual(tuple(features.columns), FEATURE_NAMES)
        self.assertTrue(features.iloc[:36].isna().any(axis=1).all())

    def test_gap_invalidates_the_following_feature_window(self):
        times = [index * 3600 for index in range(40)] + [45 * 3600 + index * 3600 for index in range(40)]
        features = calculate_features(frame(times), "H1")
        self.assertTrue(features.loc[40:74, "gap_guard"].isna().all())
        self.assertEqual(float(features.loc[76, "gap_guard"]), 0.0)


if __name__ == "__main__":
    unittest.main()

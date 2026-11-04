import unittest

from scripts.collect_mt5_market_data import validate_closed_bars


def bar(epoch, close=1.0):
    return {"time": epoch, "open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "tick_volume": 1, "spread": 2, "real_volume": 0}


class TestMt5MarketCollector(unittest.TestCase):
    def test_closed_bars_and_gaps_are_preserved(self):
        rows, gaps = validate_closed_bars([bar(1000), bar(1600)], "M5", 1900)
        self.assertEqual(len(rows), 2)
        self.assertEqual(gaps[0]["delta_seconds"], 600)

    def test_open_bar_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "open bar"):
            validate_closed_bars([bar(1000)], "M5", 1200)


if __name__ == "__main__":
    unittest.main()

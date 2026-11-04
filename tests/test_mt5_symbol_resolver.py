import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from mt5_symbol_resolver import normalized_tick_age, symbol_candidates  # noqa: E402


class TestMt5SymbolResolver(unittest.TestCase):
    def test_cent_account_prefers_sc_before_unsuffixed_symbol(self):
        candidates = symbol_candidates("XAUUSD", cent_account=True)
        self.assertEqual(candidates[:2], ["XAUUSD.sc", "XAUUSD"])

    def test_explicit_suffix_has_priority(self):
        candidates = symbol_candidates("EURUSD", suffix=".custom", cent_account=True)
        self.assertEqual(candidates[0], "EURUSD.custom")
        self.assertIn("EURUSD.sc", candidates)

    def test_normal_utc_tick_must_be_recent(self):
        age, offset = normalized_tick_age(1_000.0, 1_020.0, max_age=30.0)
        self.assertEqual((age, offset), (20.0, 0))

    def test_whole_hour_broker_timezone_is_compensated(self):
        age, offset = normalized_tick_age(8_200.0, 1_005.0, max_age=30.0)
        self.assertEqual((age, offset), (5.0, 7200))

    def test_tick_stale_after_timezone_adjustment_is_rejected(self):
        age, offset = normalized_tick_age(8_100.0, 1_000.0, max_age=30.0)
        self.assertEqual((age, offset), (None, 0))

    def test_arbitrary_future_timestamp_is_rejected(self):
        age, offset = normalized_tick_age(1_600.0, 1_000.0, max_age=30.0)
        self.assertEqual((age, offset), (None, 0))


if __name__ == "__main__":
    unittest.main()

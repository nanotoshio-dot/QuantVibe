import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import mt5_risk_state as state


class TestMt5RiskState(unittest.TestCase):
    def test_stop_locks_only_its_asset_until_next_day(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(state, "DB", Path(tmp) / "state.sqlite3"):
            state.record_signal("s1", "EURUSD", "M5", 1)
            state.record_outcome("s1", "EURUSD", "STOP_LOSS", date(2026, 11, 4))
            self.assertEqual(state.is_locked("EURUSD", date(2026, 11, 4)), (True, "STOP_LOSS"))
            self.assertEqual(state.is_locked("XAUUSD", date(2026, 11, 4)), (False, None))
            self.assertEqual(state.is_locked("EURUSD", date(2026, 11, 5)), (False, None))

    def test_take_profit_does_not_lock(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(state, "DB", Path(tmp) / "state.sqlite3"):
            state.record_signal("s2", "EURUSD", "M5", 2)
            state.record_outcome("s2", "EURUSD", "TAKE_PROFIT")
            self.assertEqual(state.is_locked("EURUSD"), (False, None))


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import mt5_outcome_observer as observer
from scripts import mt5_risk_state as state


class TestMt5OutcomeObserver(unittest.TestCase):
    def test_only_journaled_magic_stop_is_persisted(self):
        mt5 = SimpleNamespace(DEAL_ENTRY_OUT=1, DEAL_REASON_SL=4, DEAL_REASON_TP=5, history_deals_get=lambda a,b: [SimpleNamespace(magic=202609, entry=1, position_id=99, order=1, reason=4), SimpleNamespace(magic=7, entry=1, position_id=99, order=2, reason=4)])
        journal = {"o1": {"ticket": 99, "deal": 0, "symbol": "EURUSD.sc"}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(state, "DB", Path(tmp) / "state.sqlite3"):
            result = observer.observe_closed_deals(mt5, journal, 202609, datetime(2026, 11, 4, tzinfo=timezone.utc))
            self.assertEqual(result, [{"order_id": "o1", "symbol": "EURUSD.sc", "outcome": "STOP_LOSS"}])
            self.assertEqual(state.is_locked("EURUSD.sc"), (True, "STOP_LOSS"))


if __name__ == "__main__":
    unittest.main()

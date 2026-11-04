import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import update_mt5_market_history as updater


class TestMt5MarketUpdater(unittest.TestCase):
    def test_reports_only_series_with_new_closed_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history"; history.mkdir()
            (history / "manifest.json").write_text(json.dumps({"datasets": [{"asset": "EURUSD", "timeframe": "M5", "last_epoch": 100}]}), encoding="utf-8")
            def fake_collect(timeframes, count): return Path(tmp) / "capture"
            def fake_build():
                (history / "manifest.json").write_text(json.dumps({"datasets": [{"asset": "EURUSD", "timeframe": "M5", "last_epoch": 400}, {"asset": "XAUUSD", "timeframe": "M5", "last_epoch": 100}]}), encoding="utf-8")
                return history / "manifest.json"
            with patch.object(updater, "HISTORY", history), patch.object(updater, "collect", fake_collect), patch.object(updater, "build_history", fake_build):
                result = updater.update_once(["M5"], 100)
            self.assertEqual(result["series_advanced"], 2)
            self.assertEqual(result["series_total"], 2)


if __name__ == "__main__":
    unittest.main()

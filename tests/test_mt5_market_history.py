import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_mt5_market_history as history


class TestMt5MarketHistory(unittest.TestCase):
    def test_merges_overlapping_immutable_captures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, rows in (("capture_a", [(100, "1.0"), (400, "1.1")]), ("capture_b", [(400, "1.1"), (700, "1.2")])):
                capture = root / name; capture.mkdir()
                filename = "EURUSD_M5.csv"
                with (capture / filename).open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=history.COLUMNS); writer.writeheader()
                    for epoch, close in rows:
                        writer.writerow({"time": epoch, "open": close, "high": close, "low": close, "close": close, "tick_volume": 1, "spread": 1, "real_volume": 0})
                (capture / "summary.json").write_text(json.dumps({"datasets": [{"asset": "EURUSD", "timeframe": "M5", "status": "AVAILABLE_CLOSED_HISTORY", "path": filename}]}), encoding="utf-8")
            with patch.object(history, "CAPTURES", root), patch.object(history, "HISTORY", root / "history"):
                manifest = json.loads(history.build_history().read_text(encoding="utf-8"))
            self.assertEqual(manifest["datasets"][0]["rows"], 3)


if __name__ == "__main__":
    unittest.main()

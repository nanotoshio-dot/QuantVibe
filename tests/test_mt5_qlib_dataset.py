import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qlib_side import mt5_dataset


class TestMt5QlibDataset(unittest.TestCase):
    def test_loads_broker_epochs_and_reports_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / "EURUSD_M5.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]); writer.writeheader()
                for epoch in (1000, 1300, 1900): writer.writerow({"time": epoch, "open": 1, "high": 2, "low": 1, "close": 1.5, "tick_volume": 1, "spread": 1, "real_volume": 0})
            (root / "manifest.json").write_text(json.dumps({"datasets": [{"asset": "EURUSD", "timeframe": "M5", "path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}), encoding="utf-8")
            with patch.object(mt5_dataset, "HISTORY", root):
                frame, gaps, meta = mt5_dataset.load_mt5_history("EURUSD", "M5")
            self.assertEqual(len(frame), 3); self.assertEqual(len(gaps), 1); self.assertEqual(meta["gap_count"], 1)


if __name__ == "__main__":
    unittest.main()

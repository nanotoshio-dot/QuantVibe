import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts import mt5_shadow_runner as runner


class TestMt5ShadowRunner(unittest.TestCase):
    def test_blocked_series_is_persisted_once_per_closed_candle(self):
        record = {"asset": "EURUSD", "timeframe": "M5", "status": "BLOCKED", "reasons": ["insufficient_rows"]}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(runner, "DB", Path(tmp) / "shadow.sqlite3"), patch.object(runner, "assess_all", lambda: {"records": [record]}), patch.object(runner, "write_assessment", lambda: None), patch.object(runner, "load_mt5_history", lambda a, t: (pd.DataFrame({"time": [1000]}), [], {})):
                self.assertEqual(runner.run_once()["created_events"], 1)
                self.assertEqual(runner.run_once()["created_events"], 0)


if __name__ == "__main__":
    unittest.main()

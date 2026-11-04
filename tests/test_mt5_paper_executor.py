import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import mt5_paper_executor as paper


class TestMt5PaperExecutor(unittest.TestCase):
    def test_blocked_model_never_queues_order(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(paper, "DB", Path(tmp) / "paper.sqlite3"), patch.object(paper, "assess_all", lambda: {"records": [{"asset": "EURUSD", "timeframe": "M5", "status": "BLOCKED"}]}), patch.object(paper, "is_locked", lambda asset: (False, None)):
            result = paper.run_once()
        self.assertEqual(result["queued_orders"], 0)
        self.assertEqual(result["held_series"], 1)


if __name__ == "__main__":
    unittest.main()

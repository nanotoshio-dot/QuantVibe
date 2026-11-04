import json
import unittest
from pathlib import Path

from scripts.mt5_risk_policy import (
    build_budget,
    max_volume_for_stop_risk,
    validate_policy,
)


class TestMt5RiskPolicy(unittest.TestCase):
    def test_cent_account_budget_is_kept_in_raw_mt5_currency(self):
        budget = build_budget(4462.76, "USC", 0.70, 8, 0.05)
        self.assertAlmostEqual(float(budget.allocated_raw), 3123.932, places=3)
        self.assertAlmostEqual(float(budget.asset_budget_raw), 390.4915, places=4)
        self.assertAlmostEqual(float(budget.risk_per_trade_raw), 19.524575, places=5)
        self.assertAlmostEqual(float(budget.risk_per_trade_economic), 0.19524575, places=6)

    def test_volume_is_rounded_down_or_rejected(self):
        self.assertEqual(max_volume_for_stop_risk(20, 100, 0.1, 10, 0.1), 0.2)
        self.assertIsNone(max_volume_for_stop_risk(9, 100, 0.1, 10, 0.1))

    def test_policy_is_eight_assets_and_fail_closed(self):
        root = Path(__file__).resolve().parents[1]
        policy = json.loads((root / "config" / "mt5_multiasset_risk.json").read_text(encoding="utf-8"))
        validate_policy(policy)
        self.assertFalse(policy["allow_live_submission"])
        self.assertEqual(len(policy["assets"]), 8)


if __name__ == "__main__":
    unittest.main()

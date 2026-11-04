import unittest

from scripts.mt5_oos_contract import build_contract


class TestMt5OosContract(unittest.TestCase):
    def test_only_eligible_h1_records_are_bound(self):
        records = [
            {"asset": "EURUSD", "timeframe": "H1", "status": "ELIGIBLE_FOR_RESEARCH", "source_sha256": "a" * 64},
            {"asset": "AAPL", "timeframe": "M5", "status": "ELIGIBLE_FOR_RESEARCH", "source_sha256": "b" * 64},
            {"asset": "GBPUSD", "timeframe": "H1", "status": "BLOCKED", "source_sha256": "c" * 64},
        ]
        contract = build_contract(records)
        self.assertEqual(contract["binding"]["assets"], [{"asset": "EURUSD", "timeframe": "H1", "source_sha256": "a" * 64}])
        self.assertFalse(contract["execution_authorized"])
        self.assertEqual(contract["status"], "DRAFT_REQUIRES_HUMAN_APPROVAL")

    def test_hash_is_independent_of_generation_timestamp(self):
        records = [{"asset": "EURUSD", "timeframe": "H1", "status": "ELIGIBLE_FOR_RESEARCH", "source_sha256": "a" * 64}]
        self.assertEqual(build_contract(records)["contract_sha256"], build_contract(records)["contract_sha256"])


if __name__ == "__main__":
    unittest.main()

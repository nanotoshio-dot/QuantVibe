"""Create a hash-bound, human-approval-only OOS experiment contract.

The contract binds source history and research settings before a candidate is
run.  It deliberately has no approval or execution code path.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlib_side.mt5_features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from qlib_side.mt5_model_validation import assess_all
from scripts.mt5_qlib_walk_forward import ALPHAS, ONE_WAY_COST_BPS, RESEARCH_GATE, TEST_BARS, TRAIN_BARS, VALIDATION_BARS


OUTPUT = ROOT / "artifacts" / "mt5_qlib_oos_contract.draft.json"


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def build_contract(records: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [record for record in records if record["status"] == "ELIGIBLE_FOR_RESEARCH" and record["timeframe"] == "H1"]
    binding = {
        "scope": "QUANTVIBE_MT5_H1_QLIB_LINEAR_OOS_ONLY",
        "assets": [{"asset": record["asset"], "timeframe": record["timeframe"], "source_sha256": record["source_sha256"]} for record in eligible],
        "feature_schema": {"version": FEATURE_SCHEMA_VERSION, "features": list(FEATURE_NAMES)},
        "model": {"class": "qlib.contrib.model.linear.LinearModel", "estimator": "ridge", "alphas_for_inner_validation": list(ALPHAS)},
        "chronology": {"train_bars": TRAIN_BARS, "validation_bars": VALIDATION_BARS, "test_bars": TEST_BARS, "selection": "inner_validation_only", "session_gap_policy": "flat_at_non_contiguous_bar"},
        "cost_model": {"one_way_cost_bps": ONE_WAY_COST_BPS},
        "research_gate": RESEARCH_GATE,
        "exclusions": ["live_mt5_reads", "bridge_queue", "order_submission", "automatic_approval"],
    }
    return {
        "schema_version": 1,
        "status": "DRAFT_REQUIRES_HUMAN_APPROVAL",
        "execution_authorized": False,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "binding": binding,
        "contract_sha256": hashlib.sha256(_canonical(binding)).hexdigest(),
        "approval": None,
    }


def write_draft() -> Path:
    contract = build_contract(assess_all()["records"])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return OUTPUT


if __name__ == "__main__":
    print(write_draft())

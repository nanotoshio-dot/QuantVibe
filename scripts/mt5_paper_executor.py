"""Sequential paper executor for approved MT5/Qlib shadow candidates.

It never calls the bridge queue or MetaTrader5.  Without an approved model it
records HOLD, which is the expected state during history accumulation.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlib_side.mt5_model_validation import assess_all
from scripts.mt5_risk_state import is_locked


DB = ROOT / "artifacts" / "mt5_paper.sqlite3"


def run_once() -> dict[str, int | str]:
    records = assess_all()["records"]
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS paper_events (asset TEXT, timeframe TEXT, status TEXT, reason TEXT, recorded_utc TEXT, PRIMARY KEY(asset,timeframe,recorded_utc))")
        held = simulated = 0
        for record in records:
            asset, timeframe = record["asset"], record["timeframe"]
            locked, reason = is_locked(asset)
            if locked:
                status, reason = "HOLD", f"ASSET_STOP_LOCK:{reason}"
                held += 1
            elif record["status"] != "ELIGIBLE_FOR_RESEARCH":
                status, reason = "HOLD", "MODEL_NOT_ELIGIBLE"
                held += 1
            else:
                # Intentionally no generated direction/order until an approved
                # per-asset model is installed in a later phase.
                status, reason = "HOLD", "NO_APPROVED_INFERENCE_MODEL"
                held += 1
            conn.execute("INSERT INTO paper_events VALUES (?,?,?,?,?)", (asset, timeframe, status, reason, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()
    return {"mode": "PAPER", "execution_route": "none", "queued_orders": 0, "simulated_orders": simulated, "held_series": held}


if __name__ == "__main__":
    print(json.dumps(run_once()))

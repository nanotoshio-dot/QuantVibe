"""Persistent, non-trading shadow monitor for MT5/Qlib research readiness."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlib_side.mt5_dataset import load_mt5_history
from qlib_side.mt5_model_validation import assess_all, write_assessment


DB = ROOT / "artifacts" / "mt5_shadow.sqlite3"


def _connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS shadow_events (asset TEXT NOT NULL, timeframe TEXT NOT NULL, candle_epoch INTEGER NOT NULL, status TEXT NOT NULL, reason TEXT, recorded_utc TEXT NOT NULL, PRIMARY KEY(asset,timeframe,candle_epoch))")
    return conn


def run_once() -> dict[str, int]:
    eligibility = {(r["asset"], r["timeframe"]): r for r in assess_all()["records"]}
    created = held = 0
    conn = _connect()
    try:
        for (asset, timeframe), record in eligibility.items():
            frame, _, _ = load_mt5_history(asset, timeframe)
            candle = int(frame["time"].iloc[-1])
            if record["status"] != "ELIGIBLE_FOR_RESEARCH":
                status, reason = "HOLD", "MODEL_NOT_ELIGIBLE:" + ",".join(record["reasons"])
                held += 1
            else:
                # A future approved inference module may replace this state;
                # it must never be inferred from price data alone.
                status, reason = "HOLD", "NO_APPROVED_PER_ASSET_MODEL"
                held += 1
            cursor = conn.execute("INSERT OR IGNORE INTO shadow_events(asset,timeframe,candle_epoch,status,reason,recorded_utc) VALUES (?,?,?,?,?,?)", (asset, timeframe, candle, status, reason, datetime.now(timezone.utc).isoformat()))
            created += cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    write_assessment()
    return {"created_events": created, "held_series": held, "execution_authorized": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.interval_seconds < 60:
        parser.error("--interval-seconds must be at least 60")
    while True:
        print(json.dumps(run_once()))
        if not args.watch:
            return 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

"""Persistent per-asset signal/outcome state; no MT5 or trading APIs."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "artifacts" / "mt5_risk_state.sqlite3"


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS signals (signal_id TEXT PRIMARY KEY, asset TEXT NOT NULL, timeframe TEXT NOT NULL, candle_epoch INTEGER NOT NULL, status TEXT NOT NULL, created_utc TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS outcomes (signal_id TEXT NOT NULL, outcome TEXT NOT NULL, recorded_utc TEXT NOT NULL, PRIMARY KEY(signal_id,outcome))")
    conn.execute("CREATE TABLE IF NOT EXISTS asset_locks (asset TEXT PRIMARY KEY, locked_until_day TEXT NOT NULL, reason TEXT NOT NULL, signal_id TEXT NOT NULL, recorded_utc TEXT NOT NULL)")
    return conn


def record_signal(signal_id: str, asset: str, timeframe: str, candle_epoch: int, status: str = "SHADOW") -> bool:
    conn = _conn()
    try:
        cursor = conn.execute("INSERT OR IGNORE INTO signals VALUES (?,?,?,?,?,?)", (signal_id, asset.upper(), timeframe.upper(), int(candle_epoch), status, datetime.now(timezone.utc).isoformat()))
        conn.commit(); return bool(cursor.rowcount)
    finally:
        conn.close()


def record_outcome(signal_id: str, asset: str, outcome: str, trading_day: date | None = None) -> bool:
    """Persist outcome. STOP_LOSS locks only this asset through the given day."""
    outcome = outcome.upper()
    if outcome not in {"STOP_LOSS", "TAKE_PROFIT", "CLOSED_OTHER", "REJECTED"}:
        raise ValueError("unsupported outcome")
    today = trading_day or datetime.now(timezone.utc).date()
    conn = _conn()
    try:
        cursor = conn.execute("INSERT OR IGNORE INTO outcomes VALUES (?,?,?)", (signal_id, outcome, datetime.now(timezone.utc).isoformat()))
        if cursor.rowcount and outcome == "STOP_LOSS":
            conn.execute("INSERT INTO asset_locks(asset,locked_until_day,reason,signal_id,recorded_utc) VALUES (?,?,?,?,?) ON CONFLICT(asset) DO UPDATE SET locked_until_day=excluded.locked_until_day,reason=excluded.reason,signal_id=excluded.signal_id,recorded_utc=excluded.recorded_utc", (asset.upper(), today.isoformat(), "STOP_LOSS", signal_id, datetime.now(timezone.utc).isoformat()))
        conn.commit(); return bool(cursor.rowcount)
    finally:
        conn.close()


def is_locked(asset: str, trading_day: date | None = None) -> tuple[bool, str | None]:
    day = trading_day or datetime.now(timezone.utc).date()
    conn = _conn()
    try:
        row = conn.execute("SELECT locked_until_day,reason FROM asset_locks WHERE asset=?", (asset.upper(),)).fetchone()
        if not row or date.fromisoformat(row[0]) < day:
            return False, None
        return True, str(row[1])
    finally:
        conn.close()

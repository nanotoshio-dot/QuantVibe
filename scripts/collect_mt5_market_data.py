"""Read-only, closed-candle MT5 collector for QuantVibe research.

It deliberately has no order, position, symbol-selection or model APIs.  Each
run creates a new hash-verified snapshot under data/mt5_market; it never
overwrites a previous capture and must not be treated as a live trading feed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from scripts.mt5_symbol_resolver import resolve_mt5_symbol
from scripts.mt5_project_universe import project_assets


OUTPUT_ROOT = ROOT / "data" / "mt5_market"
TERMINAL = Path(r"C:\Program Files\Vantage International MT5\terminal64.exe")
EXPECTED_SERVER = "VantageMarkets-Live 5"
SECONDS = {"M5": 300, "M15": 900, "H1": 3600}


def _field(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row[name]
    return row[name]


def validate_closed_bars(rates: Iterable[Any], timeframe: str, successor_open: int) -> tuple[list[dict[str, Any]], list[dict[str, int]]]:
    """Validate immutable raw broker bars and return gaps without filling them."""
    if timeframe not in SECONDS:
        raise ValueError("unsupported timeframe")
    required = ("time", "open", "high", "low", "close", "tick_volume")
    rows: list[dict[str, Any]] = []
    previous: int | None = None
    gaps: list[dict[str, int]] = []
    for item in rates:
        try:
            row = {key: _field(item, key) for key in required}
            for optional in ("spread", "real_volume"):
                try:
                    row[optional] = _field(item, optional)
                except (KeyError, ValueError, IndexError):
                    pass
            epoch = int(row["time"])
            if epoch <= 0 or epoch != row["time"]:
                raise ValueError("invalid epoch")
            numeric = [float(row[key]) for key in ("open", "high", "low", "close", "tick_volume")]
            if not all(math.isfinite(value) for value in numeric):
                raise ValueError("nonfinite bar")
            if min(numeric[:4]) <= 0 or float(row["high"]) < max(numeric[:4]) or float(row["low"]) > min(numeric[:4]):
                raise ValueError("invalid OHLC")
            if float(row["tick_volume"]) < 0 or any(float(row[key]) < 0 for key in ("spread", "real_volume") if key in row):
                raise ValueError("invalid volume or spread")
            if epoch + SECONDS[timeframe] > successor_open:
                raise ValueError("open bar included")
            if previous is not None:
                delta = epoch - previous
                if delta <= 0:
                    raise ValueError("duplicate or unordered bars")
                if delta != SECONDS[timeframe]:
                    gaps.append({"previous_epoch": previous, "next_epoch": epoch, "delta_seconds": delta})
            previous = epoch
            rows.append(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid MT5 bar: {exc}") from exc
    if not rows:
        raise ValueError("no closed data or session unavailable")
    return rows, gaps


def _assets() -> list[dict[str, str]]:
    policy_path = ROOT / "config" / "mt5_multiasset_risk.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    return [dict(item) for item in policy["assets"]]


def collect(timeframes: list[str], count: int, assets: list[dict[str, str]] | None = None) -> Path:
    if not 1 <= count <= 5000 or not timeframes or any(tf not in SECONDS for tf in timeframes):
        raise ValueError("invalid count or timeframe")
    import MetaTrader5 as mt5

    if not TERMINAL.is_file() or not mt5.initialize(path=str(TERMINAL), timeout=10_000):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        terminal, account = mt5.terminal_info(), mt5.account_info()
        if terminal is None or account is None or not terminal.connected:
            raise RuntimeError("MT5 disconnected or account unavailable")
        if str(account.server) != EXPECTED_SERVER:
            raise RuntimeError("unexpected MT5 server")
        if str(account.currency).upper() not in {"USC", "USD"}:
            raise RuntimeError("unexpected account currency")

        capture_dir = OUTPUT_ROOT / ("capture_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8])
        capture_dir.mkdir(parents=True, exist_ok=False)
        summary: dict[str, Any] = {
            "schema_version": 1, "captured_utc": datetime.now(timezone.utc).isoformat(),
            "terminal": str(TERMINAL), "server": str(account.server), "currency": str(account.currency),
            "trading_enabled": False, "clock": "broker_epochs_preserved_unverified_utc", "datasets": [],
        }
        # ``[]`` is a valid caller choice (collect nothing).  Do not turn it
        # into the risk-policy universe through truthiness; that would make a
        # scheduler collect a different universe than the one it reports.
        for asset in (assets if assets is not None else _assets()):
            logical = asset["instrument"].upper()
            requested = asset.get("broker_symbol") or logical
            symbol = resolve_mt5_symbol(mt5, requested, cent_account=str(account.currency).upper() == "USC")
            if not symbol:
                summary["datasets"].append({"asset": logical, "status": "UNAVAILABLE", "reason": "symbol_not_visible_or_missing"})
                continue
            for timeframe in timeframes:
                tf = getattr(mt5, "TIMEFRAME_" + timeframe)
                anchor = mt5.copy_rates_from_pos(symbol, tf, 0, 2)
                if anchor is None or len(anchor) != 2:
                    summary["datasets"].append({"asset": logical, "symbol": symbol, "timeframe": timeframe, "status": "UNAVAILABLE", "reason": "no_closed_anchor"})
                    continue
                closed_anchor, successor = int(anchor[0]["time"]), int(anchor[1]["time"])
                rates = mt5.copy_rates_from(symbol, tf, datetime.fromtimestamp(closed_anchor, timezone.utc), count)
                if rates is None:
                    summary["datasets"].append({"asset": logical, "symbol": symbol, "timeframe": timeframe, "status": "UNAVAILABLE", "reason": "rates_query_failed"})
                    continue
                rows, gaps = validate_closed_bars(rates, timeframe, successor)
                if int(rows[-1]["time"]) != closed_anchor:
                    raise RuntimeError("closed anchor changed during download")
                csv_path = capture_dir / f"{logical}_{timeframe}.csv"
                columns = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
                with csv_path.open("x", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
                    writer.writeheader(); writer.writerows(rows)
                digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
                summary["datasets"].append({"asset": logical, "symbol": symbol, "timeframe": timeframe, "status": "AVAILABLE_CLOSED_HISTORY", "rows": len(rows), "closed_anchor_epoch": closed_anchor, "successor_open_epoch": successor, "gap_count": len(gaps), "gaps": gaps, "sha256": digest, "path": csv_path.name})
        (capture_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return capture_dir
    finally:
        mt5.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframes", nargs="+", default=["M5", "H1"])
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--all-project-assets", action="store_true", help="collect configured universe; does not change trading/risk universe")
    args = parser.parse_args()
    try:
        path = collect(args.timeframes, args.count, project_assets() if args.all_project_assets else None)
        print(f"READ-ONLY MT5 capture written: {path}")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"COLLECTION BLOCKED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

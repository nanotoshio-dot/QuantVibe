"""Read MT5 deal history for QuantVibe journal entries only; never trades."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mt5_risk_state import record_outcome


def _value(deal: Any, name: str, default=None):
    return getattr(deal, name, default)


def classify_deal(mt5: Any, deal: Any) -> str:
    reason = _value(deal, "reason")
    if reason == getattr(mt5, "DEAL_REASON_SL", object()):
        return "STOP_LOSS"
    if reason == getattr(mt5, "DEAL_REASON_TP", object()):
        return "TAKE_PROFIT"
    return "CLOSED_OTHER"


def observe_closed_deals(mt5: Any, executed_orders: dict[str, dict], magic: int, now: datetime | None = None) -> list[dict[str, str]]:
    """Persist outcomes for journaled orders only; unknown data never becomes SL/TP."""
    now = now or datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=7), now)
    if deals is None:
        return []
    results: list[dict[str, str]] = []
    out_entry = getattr(mt5, "DEAL_ENTRY_OUT", 1)
    for order_id, entry in executed_orders.items():
        known = {int(entry.get(key) or 0) for key in ("ticket", "deal")}
        for deal in deals:
            if int(_value(deal, "magic", -1)) != int(magic):
                continue
            if _value(deal, "entry") != out_entry:
                continue
            if int(_value(deal, "position_id", 0)) not in known and int(_value(deal, "order", 0)) not in known:
                continue
            outcome = classify_deal(mt5, deal)
            if record_outcome(order_id, str(entry.get("symbol") or ""), outcome):
                results.append({"order_id": order_id, "symbol": str(entry.get("symbol") or ""), "outcome": outcome})
    return results

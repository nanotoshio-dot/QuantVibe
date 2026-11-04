"""Pure, fail-closed capital and stop-risk policy for the MT5 executor.

This module deliberately contains no MT5 calls and never submits orders.  The
bridge/executor must obtain price, stop distance and tick value from MT5, then
use these calculations to decide whether a candidate is eligible.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping


CENT_CURRENCIES = {"USC", "EUC", "GBC"}


@dataclass(frozen=True)
class RiskBudget:
    account_currency: str
    cent_divider: Decimal
    balance_raw: Decimal
    allocated_raw: Decimal
    asset_budget_raw: Decimal
    risk_per_trade_raw: Decimal
    max_active_assets: int

    @property
    def allocated_economic(self) -> Decimal:
        return self.allocated_raw / self.cent_divider

    @property
    def asset_budget_economic(self) -> Decimal:
        return self.asset_budget_raw / self.cent_divider

    @property
    def risk_per_trade_economic(self) -> Decimal:
        return self.risk_per_trade_raw / self.cent_divider


def cent_divider_for_currency(currency: str) -> Decimal:
    return Decimal("100") if str(currency or "").upper() in CENT_CURRENCIES else Decimal("1")


def build_budget(
    balance_raw: float | Decimal,
    currency: str,
    allocation_pct: float | Decimal = Decimal("0.70"),
    max_active_assets: int = 8,
    risk_per_trade_pct_of_asset_budget: float | Decimal = Decimal("0.05"),
) -> RiskBudget:
    balance = Decimal(str(balance_raw))
    allocation = Decimal(str(allocation_pct))
    risk_pct = Decimal(str(risk_per_trade_pct_of_asset_budget))
    if balance <= 0:
        raise ValueError("MT5 balance must be positive")
    if not Decimal("0") < allocation <= Decimal("1"):
        raise ValueError("allocation_pct must be in (0, 1]")
    if max_active_assets < 1:
        raise ValueError("max_active_assets must be at least 1")
    if not Decimal("0") < risk_pct <= Decimal("1"):
        raise ValueError("risk_per_trade_pct_of_asset_budget must be in (0, 1]")

    allocated = balance * allocation
    asset_budget = allocated / Decimal(max_active_assets)
    return RiskBudget(
        account_currency=str(currency or "").upper(),
        cent_divider=cent_divider_for_currency(currency),
        balance_raw=balance,
        allocated_raw=allocated,
        asset_budget_raw=asset_budget,
        risk_per_trade_raw=asset_budget * risk_pct,
        max_active_assets=max_active_assets,
    )


def floor_to_volume_step(volume: float, min_volume: float, max_volume: float, step: float) -> float | None:
    """Round down: risk sizing must never make a lot larger than approved."""
    v = Decimal(str(volume))
    lo = Decimal(str(min_volume))
    hi = Decimal(str(max_volume))
    increment = Decimal(str(step))
    if lo <= 0 or hi < lo or increment <= 0:
        raise ValueError("invalid MT5 volume limits")
    if v < lo:
        return None
    floored = (v / increment).to_integral_value(rounding=ROUND_DOWN) * increment
    if floored < lo:
        return None
    return float(min(floored, hi))


def max_volume_for_stop_risk(
    risk_budget_raw: float,
    loss_at_one_lot_raw: float,
    min_volume: float,
    max_volume: float,
    volume_step: float,
) -> float | None:
    """Return the largest valid lot whose worst loss at SL fits the budget."""
    budget = Decimal(str(risk_budget_raw))
    one_lot_loss = Decimal(str(loss_at_one_lot_raw))
    if budget <= 0 or one_lot_loss <= 0:
        return None
    return floor_to_volume_step(
        float(budget / one_lot_loss), min_volume, max_volume, volume_step
    )


def summarize_budget(budget: RiskBudget) -> dict[str, Any]:
    return {
        "account_currency": budget.account_currency,
        "cent_divider": float(budget.cent_divider),
        "balance_raw": float(budget.balance_raw),
        "allocated_raw": float(budget.allocated_raw),
        "asset_budget_raw": float(budget.asset_budget_raw),
        "risk_per_trade_raw": float(budget.risk_per_trade_raw),
        "allocated_economic": float(budget.allocated_economic),
        "asset_budget_economic": float(budget.asset_budget_economic),
        "risk_per_trade_economic": float(budget.risk_per_trade_economic),
        "max_active_assets": budget.max_active_assets,
    }


def validate_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("one_stop_lock_scope") != "asset_until_next_trading_day":
        raise ValueError("one_stop_lock_scope must lock only the stopped asset")
    if policy.get("single_inflight_order") is not True:
        raise ValueError("single_inflight_order must be enabled")
    assets = policy.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("policy must define assets")
    limit = int(policy.get("max_active_assets") or 0)
    if len(assets) > limit:
        raise ValueError("assets cannot exceed max_active_assets")
    build_budget(
        1,
        str(policy.get("account_currency") or "USD"),
        policy.get("capital_allocation_pct", 0.70),
        limit,
        policy.get("risk_per_trade_pct_of_asset_budget", 0.05),
    )

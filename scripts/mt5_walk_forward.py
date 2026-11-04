"""Offline walk-forward baseline for eligible MT5 H1 research series.

This is deliberately not an execution engine: it imports neither MetaTrader5
nor the bridge.  It evaluates a simple, fully disclosed momentum baseline so
that a future Qlib model has a reproducible benchmark to beat.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlib_side.mt5_dataset import SECONDS, load_mt5_history
from qlib_side.mt5_model_validation import assess_all


OUTPUT = ROOT / "artifacts" / "mt5_walk_forward.json"
PARAMETERS = ((12, 48), (20, 80), (40, 160))
TRAIN_BARS = 2_000
TEST_BARS = 500
ROUND_TRIP_COST_BPS = 4.0


def strategy_returns(frame: pd.DataFrame, timeframe: str, fast: int, slow: int, cost_bps: float = ROUND_TRIP_COST_BPS) -> pd.DataFrame:
    """Long/short close-to-close simulation, using only already closed bars.

    Signals are shifted one bar, and a position is forcibly flat across every
    detected session boundary.  Therefore neither an open candle nor an
    unobserved overnight price jump becomes an implicit live-trading claim.
    """
    if fast >= slow or fast < 2 or len(frame) <= slow:
        raise ValueError("invalid momentum windows or insufficient history")
    out = frame[["time", "close"]].copy().reset_index(drop=True)
    close = out["close"].astype(float)
    signal = np.where(close.rolling(fast).mean() > close.rolling(slow).mean(), 1.0, -1.0)
    position = pd.Series(signal, index=out.index).shift(1).fillna(0.0)
    boundaries = out["time"].astype("int64").diff().fillna(SECONDS[timeframe]) != SECONDS[timeframe]
    # A boundary is between i-1 and i: do not carry i-1's position across it.
    position.loc[boundaries] = 0.0
    returns = close.pct_change().fillna(0.0)
    turnover = position.diff().abs().fillna(position.abs())
    cost = turnover * (cost_bps / 20_000.0)  # bps per one-way position change
    out["position"] = position
    out["strategy_return"] = position * returns - cost
    out["turnover"] = turnover
    return out


def metrics(results: pd.DataFrame) -> dict[str, float | int]:
    returns = results["strategy_return"].astype(float)
    equity = (1.0 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    active = results.loc[results["position"] != 0.0, "strategy_return"]
    return {
        "bars": int(len(results)),
        "total_return": float(equity.iloc[-1] - 1.0) if len(equity) else 0.0,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        "bar_sharpe": float(returns.mean() / returns.std(ddof=1)) if len(returns) > 1 and returns.std(ddof=1) > 0 else 0.0,
        "turnover": float(results["turnover"].sum()),
        "active_bar_win_rate": float((active > 0).mean()) if len(active) else 0.0,
    }


def _choose_parameters(train: pd.DataFrame, timeframe: str) -> tuple[int, int]:
    candidates = []
    for fast, slow in PARAMETERS:
        result = strategy_returns(train, timeframe, fast, slow)
        candidates.append((metrics(result)["bar_sharpe"], fast, slow))
    _, fast, slow = max(candidates, key=lambda item: (item[0], -item[2], -item[1]))
    return fast, slow


def walk_forward(asset: str, timeframe: str, frame: pd.DataFrame) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    start = TRAIN_BARS
    while start + TEST_BARS <= len(frame):
        train = frame.iloc[:start].copy()
        test = frame.iloc[start : start + TEST_BARS].copy()
        fast, slow = _choose_parameters(train, timeframe)
        # Include past bars only for indicator warm-up, then score exactly test.
        context = pd.concat([frame.iloc[max(0, start - slow) : start], test], ignore_index=True)
        result = strategy_returns(context, timeframe, fast, slow).iloc[-len(test) :].reset_index(drop=True)
        folds.append({
            "train_end_epoch": int(train["time"].iloc[-1]), "test_start_epoch": int(test["time"].iloc[0]),
            "test_end_epoch": int(test["time"].iloc[-1]), "parameters": {"fast": fast, "slow": slow},
            "metrics": metrics(result),
        })
        start += TEST_BARS
    if not folds:
        raise ValueError("insufficient rows for configured walk-forward windows")
    total_return = math.prod(1.0 + fold["metrics"]["total_return"] for fold in folds) - 1.0
    return {
        "asset": asset, "timeframe": timeframe, "folds": folds, "fold_count": len(folds),
        "aggregate": {
            "compounded_return": total_return,
            "mean_fold_return": float(np.mean([fold["metrics"]["total_return"] for fold in folds])),
            "worst_fold_drawdown": float(min(fold["metrics"]["max_drawdown"] for fold in folds)),
            "mean_bar_sharpe": float(np.mean([fold["metrics"]["bar_sharpe"] for fold in folds])),
        },
    }


def run() -> dict[str, Any]:
    records = [r for r in assess_all()["records"] if r["status"] == "ELIGIBLE_FOR_RESEARCH" and r["timeframe"] == "H1"]
    results = []
    for record in records:
        frame, _, metadata = load_mt5_history(record["asset"], record["timeframe"])
        report = walk_forward(record["asset"], record["timeframe"], frame)
        report["source_sha256"] = metadata["source_sha256"]
        results.append(report)
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(), "mode": "OFFLINE_RESEARCH_BASELINE",
        "execution_authorized": False, "mt5_accessed": False,
        "cost_model": {"round_trip_cost_bps": ROUND_TRIP_COST_BPS, "position_flat_at_session_boundary": True},
        "limitations": ["broker_bar_open_epochs_are_unverified_utc", "baseline_is_not_a_qlib_model", "results_are_not_trade_authorization"],
        "results": results,
    }


if __name__ == "__main__":
    result = run(); OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8"); print(OUTPUT)

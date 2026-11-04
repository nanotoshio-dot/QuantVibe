"""Offline per-asset Qlib LinearModel walk-forward research benchmark.

No MetaTrader5 or bridge import is permitted here.  This module is a research
gate only; it writes no signal that an execution component may consume.
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
from qlib_side.mt5_features import FEATURE_SCHEMA_VERSION, calculate_features
from qlib_side.mt5_model_validation import assess_all


OUTPUT = ROOT / "artifacts" / "mt5_qlib_walk_forward.json"
TRAIN_BARS, VALIDATION_BARS, TEST_BARS = 2_000, 250, 500
ONE_WAY_COST_BPS = 2.0
RESEARCH_GATE = {"min_folds": 6, "min_compounded_return": 0.0, "max_worst_fold_drawdown": -0.10, "min_mean_bar_sharpe": 0.0}
ALPHAS = (0.01, 0.1, 1.0)
VOLATILITY_QUANTILES = (1.0, 0.90, 0.75)


def feature_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Features observed at a bar close and a one-bar-ahead research label."""
    close = frame["close"].astype(float)
    features = calculate_features(frame, "H1")
    label = close.shift(-1) / close - 1.0
    return features.replace([np.inf, -np.inf], np.nan), label.replace([np.inf, -np.inf], np.nan)


def qlib_predictions(asset: str, frame: pd.DataFrame, train_end: int, test_end: int, alpha: float = 0.1) -> np.ndarray:
    """Fit Qlib LinearModel strictly through train_end and predict the next range."""
    from qlib.contrib.model.linear import LinearModel
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.data.dataset.loader import StaticDataLoader

    features, label = feature_frame(frame.iloc[:test_end].reset_index(drop=True))
    indexed = features.copy()
    indexed.index = pd.MultiIndex.from_arrays(
        [pd.to_datetime(frame.iloc[:test_end]["time"].to_numpy(), unit="s"), [asset] * len(indexed)],
        names=["datetime", "instrument"],
    )
    labels = pd.DataFrame({"LABEL0": label.to_numpy()}, index=indexed.index)
    payload = pd.concat({"feature": indexed, "label": labels}, axis=1)
    loader = StaticDataLoader(config=payload)
    handler = DataHandlerLP(data_loader=loader, infer_processors=[], learn_processors=[], shared_processors=[])
    times = indexed.index.get_level_values("datetime")
    dataset = DatasetH(handler=handler, segments={
        "train": (times[0], times[train_end - 1]),
        "test": (times[train_end], times[test_end - 1]),
    })
    model = LinearModel(estimator="ridge", alpha=alpha)
    model.fit(dataset)
    predicted = model.predict(dataset, segment="test")
    values = np.asarray(predicted, dtype=float).reshape(-1)
    expected = test_end - train_end
    if len(values) != expected:
        raise RuntimeError(f"Qlib prediction alignment failed: expected {expected}, got {len(values)}")
    return values


def simulate_predictions(test: pd.DataFrame, predictions: np.ndarray, timeframe: str, volatility_limit: float | None = None) -> dict[str, float | int]:
    """Execute hypothetical next-bar positions; flat across non-contiguous bars."""
    prices = test["close"].astype(float).reset_index(drop=True)
    signal = np.sign(pd.Series(predictions)).fillna(0.0)
    if volatility_limit is not None:
        volatility = test["close"].astype(float).pct_change().rolling(20).std().reset_index(drop=True)
        signal.loc[volatility > volatility_limit] = 0.0
    position = signal.shift(1).fillna(0.0)
    boundaries = test["time"].astype("int64").reset_index(drop=True).diff().fillna(SECONDS[timeframe]) != SECONDS[timeframe]
    position.loc[boundaries] = 0.0
    turnover = position.diff().abs().fillna(position.abs())
    returns = position * prices.pct_change().fillna(0.0) - turnover * (ONE_WAY_COST_BPS / 10_000.0)
    equity = (1 + returns).cumprod(); drawdown = equity / equity.cummax() - 1
    active = returns[position != 0]
    return {
        "bars": len(test), "total_return": float(equity.iloc[-1] - 1), "max_drawdown": float(drawdown.min()),
        "bar_sharpe": float(returns.mean() / returns.std(ddof=1)) if returns.std(ddof=1) > 0 else 0.0,
        "turnover": float(turnover.sum()), "active_bar_win_rate": float((active > 0).mean()) if len(active) else 0.0,
    }


def walk_forward(asset: str, timeframe: str, frame: pd.DataFrame) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    start = TRAIN_BARS
    while start + VALIDATION_BARS + TEST_BARS <= len(frame):
        validation_end = start + VALIDATION_BARS
        choices = []
        historical_vol = frame.iloc[:start]["close"].astype(float).pct_change().rolling(20).std()
        for alpha in ALPHAS:
            validation_predictions = qlib_predictions(asset, frame, start, validation_end, alpha)
            validation = frame.iloc[start:validation_end].reset_index(drop=True)
            for quantile in VOLATILITY_QUANTILES:
                limit = None if quantile == 1.0 else float(historical_vol.quantile(quantile))
                choices.append((simulate_predictions(validation, validation_predictions, timeframe, limit)["bar_sharpe"], alpha, quantile, limit))
        _, alpha, quantile, limit = max(choices, key=lambda choice: (choice[0], -choice[1], choice[2]))
        end = validation_end + TEST_BARS
        # Refit through the validation period only after its selection decision
        # has been made; the following test bars remain completely unseen.
        predictions = qlib_predictions(asset, frame, validation_end, end, alpha)
        test = frame.iloc[validation_end:end].reset_index(drop=True)
        folds.append({"train_end_epoch": int(frame["time"].iloc[validation_end - 1]), "test_end_epoch": int(test["time"].iloc[-1]),
                      "selected": {"alpha": alpha, "volatility_quantile": quantile, "volatility_limit": limit},
                      "metrics": simulate_predictions(test, predictions, timeframe, limit)})
        start += TEST_BARS
    if not folds:
        raise ValueError("insufficient history for Qlib walk-forward")
    aggregate = {"compounded_return": math.prod(1 + fold["metrics"]["total_return"] for fold in folds) - 1,
                 "worst_fold_drawdown": min(fold["metrics"]["max_drawdown"] for fold in folds),
                 "mean_bar_sharpe": float(np.mean([fold["metrics"]["bar_sharpe"] for fold in folds]))}
    failures = []
    if len(folds) < RESEARCH_GATE["min_folds"]: failures.append("insufficient_folds")
    if aggregate["compounded_return"] <= RESEARCH_GATE["min_compounded_return"]: failures.append("non_positive_return")
    if aggregate["worst_fold_drawdown"] < RESEARCH_GATE["max_worst_fold_drawdown"]: failures.append("excessive_drawdown")
    if aggregate["mean_bar_sharpe"] <= RESEARCH_GATE["min_mean_bar_sharpe"]: failures.append("non_positive_sharpe")
    return {"asset": asset, "timeframe": timeframe, "fold_count": len(folds), "folds": folds, "aggregate": aggregate,
            "research_gate": {"passed": not failures, "failures": failures, "thresholds": RESEARCH_GATE}}


def run() -> dict[str, Any]:
    records = [r for r in assess_all()["records"] if r["status"] == "ELIGIBLE_FOR_RESEARCH" and r["timeframe"] == "H1"]
    results = []
    for record in records:
        frame, _, metadata = load_mt5_history(record["asset"], "H1")
        result = walk_forward(record["asset"], "H1", frame); result["source_sha256"] = metadata["source_sha256"]; results.append(result)
    return {"generated_utc": datetime.now(timezone.utc).isoformat(), "mode": "OFFLINE_QLIB_RESEARCH", "execution_authorized": False, "mt5_accessed": False,
            "model": "qlib.contrib.model.linear.LinearModel(ridge)", "feature_schema_version": FEATURE_SCHEMA_VERSION, "one_way_cost_bps": ONE_WAY_COST_BPS,
            "limitations": ["broker_epochs_unverified_utc", "research_result_is_not_trade_authorization"], "results": results}


if __name__ == "__main__":
    report = run(); OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8"); print(OUTPUT)

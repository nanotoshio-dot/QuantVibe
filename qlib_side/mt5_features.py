"""Versioned causal feature schema for QuantVibe MT5 research.

Every value at row t uses t or earlier closed bars only.  Session gaps are
made explicit: no feature is silently carried through a discontinuity.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from qlib_side.mt5_dataset import SECONDS


FEATURE_SCHEMA_VERSION = "MT5_CAUSAL_FEATURES_V1"
FEATURE_NAMES = (
    "ret_1", "ret_3", "ret_6", "ret_12", "range_pct", "body_pct",
    "range_mean_3", "range_mean_6", "range_mean_12", "range_mean_36",
    "range_expansion_3_12", "range_expansion_6_36", "ret_std_6",
    "ret_std_12", "ret_std_36", "distance_ma_12", "distance_ma_36",
    "tick_volume_ratio_12", "tick_volume_mean_3_12", "tick_volume_mean_6_36",
    "spread_pct", "gap_guard",
)
MIN_EXPECTED_SESSION_BREAK_SECONDS = {"M5": 7_200, "M15": 14_400, "H1": 28_800}


def calculate_features(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Return immutable-order, causal features; gaps invalidate a 36-bar window."""
    required = {"time", "open", "high", "low", "close", "tick_volume", "spread"}
    if timeframe not in SECONDS or not required.issubset(frame.columns):
        raise ValueError("unsupported timeframe or missing MT5 feature columns")
    data = frame.reset_index(drop=True)
    close, open_ = data["close"].astype(float), data["open"].astype(float)
    high, low = data["high"].astype(float), data["low"].astype(float)
    volume, spread = data["tick_volume"].astype(float), data["spread"].astype(float)
    ret = close.pct_change()
    range_pct = (high - low) / close
    features = pd.DataFrame({
        "ret_1": ret, "ret_3": close.pct_change(3), "ret_6": close.pct_change(6), "ret_12": close.pct_change(12),
        "range_pct": range_pct, "body_pct": (close - open_) / open_,
        "range_mean_3": range_pct.rolling(3).mean(), "range_mean_6": range_pct.rolling(6).mean(),
        "range_mean_12": range_pct.rolling(12).mean(), "range_mean_36": range_pct.rolling(36).mean(),
        "range_expansion_3_12": range_pct.rolling(3).mean() / range_pct.rolling(12).mean() - 1.0,
        "range_expansion_6_36": range_pct.rolling(6).mean() / range_pct.rolling(36).mean() - 1.0,
        "ret_std_6": ret.rolling(6).std(), "ret_std_12": ret.rolling(12).std(), "ret_std_36": ret.rolling(36).std(),
        "distance_ma_12": close / close.rolling(12).mean() - 1.0, "distance_ma_36": close / close.rolling(36).mean() - 1.0,
        "tick_volume_ratio_12": volume / volume.rolling(12).mean(),
        "tick_volume_mean_3_12": volume.rolling(3).mean() / volume.rolling(12).mean(),
        "tick_volume_mean_6_36": volume.rolling(6).mean() / volume.rolling(36).mean(),
        "spread_pct": spread / close,
    })
    delta = data["time"].astype("int64").diff()
    # A long exchange/market close is retained as a visible session boundary.
    # Only short unexplained holes poison the causal feature window.
    unexpected_gap = delta.ne(SECONDS[timeframe]) & delta.lt(MIN_EXPECTED_SESSION_BREAK_SECONDS[timeframe])
    gap_free = (~unexpected_gap).rolling(36, min_periods=36).sum().eq(36)
    features["gap_guard"] = np.where(gap_free, 0.0, np.nan)
    return features.loc[:, FEATURE_NAMES].replace([np.inf, -np.inf], np.nan)

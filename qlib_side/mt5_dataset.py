"""Qlib research adapter for immutable MT5 market history.

The source timestamps are raw MT5 broker epochs.  They are deliberately not
marketed as verified historical UTC and this module has no training/inference
or execution entry point.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data" / "mt5_market" / "history"
SECONDS = {"M5": 300, "M15": 900, "H1": 3600}


def load_mt5_history(asset: str, timeframe: str, require_continuous: bool = False) -> tuple[pd.DataFrame, list[dict[str, int]], dict[str, Any]]:
    """Load one logical asset/timeframe and expose gaps instead of hiding them."""
    asset, timeframe = asset.upper(), timeframe.upper()
    if timeframe not in SECONDS:
        raise ValueError("unsupported timeframe")
    manifest = json.loads((HISTORY / "manifest.json").read_text(encoding="utf-8"))
    item = next((row for row in manifest["datasets"] if row["asset"] == asset and row["timeframe"] == timeframe), None)
    if item is None:
        raise FileNotFoundError(f"no MT5 history for {asset} {timeframe}")
    frame = pd.read_csv(HISTORY / item["path"]).sort_values("time").reset_index(drop=True)
    required = {"time", "open", "high", "low", "close", "tick_volume"}
    if not required.issubset(frame.columns) or frame.empty:
        raise ValueError("invalid MT5 history schema")
    required_columns = sorted(required)
    if frame[required_columns].isnull().any().any() or not frame[required_columns].apply(pd.to_numeric, errors="coerce").notnull().all().all():
        raise ValueError("non-numeric or missing MT5 history")
    delta = frame["time"].astype("int64").diff()
    gaps = [
        {"previous_epoch": int(frame.loc[index - 1, "time"]), "next_epoch": int(frame.loc[index, "time"]), "delta_seconds": int(delta.loc[index])}
        for index in range(1, len(frame)) if int(delta.loc[index]) != SECONDS[timeframe]
    ]
    if require_continuous and gaps:
        raise ValueError(f"history has {len(gaps)} gaps; continuous dataset required")
    metadata = {
        "asset": asset, "timeframe": timeframe, "rows": len(frame), "gap_count": len(gaps),
        "source_sha256": item["sha256"], "timestamp_semantics": "BROKER_BAR_OPEN_EPOCH_UNVERIFIED_UTC",
        "data_source": "mt5_closed_history", "trading_enabled": False,
    }
    return frame, gaps, metadata


def qlib_static_dataset(asset: str, timeframe: str, require_continuous: bool = False):
    """Create a Qlib StaticDataLoader dataset without converting timestamps or fitting a model."""
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.data.dataset.loader import StaticDataLoader

    frame, gaps, metadata = load_mt5_history(asset, timeframe, require_continuous)
    values = frame.drop(columns=["time"]).copy()
    values["volume"] = values["tick_volume"]  # Explicit tick-count alias.
    values.index = pd.MultiIndex.from_arrays(
        [pd.to_datetime(frame["time"], unit="s"), [asset] * len(frame)], names=["datetime", "instrument"]
    )
    loader = StaticDataLoader(config=pd.concat({"feature": values}, axis=1))
    handler = DataHandlerLP(data_loader=loader, infer_processors=[], learn_processors=[], shared_processors=[])
    dataset = DatasetH(handler=handler, segments={"data": (values.index[0][0], values.index[-1][0])})
    prepared = dataset.prepare("data", col_set="feature", data_key=DataHandlerLP.DK_I)
    if not prepared.equals(values):
        raise RuntimeError("Qlib dataset round-trip mismatch")
    return dataset, prepared, gaps, metadata

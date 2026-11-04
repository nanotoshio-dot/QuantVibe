"""Fail-closed eligibility gate for per-asset MT5/Qlib research models.

This is intentionally separate from the daily US-equity pipeline.  Passing this
gate makes a series eligible for a future chronological research run; it never
means that an order may be sent.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlib_side.mt5_dataset import HISTORY, SECONDS, load_mt5_history


MIN_ROWS = {"M5": 20_000, "M15": 10_000, "H1": 5_000}
MIN_CONTIGUOUS_ROWS = {"M5": 2_000, "M15": 1_000, "H1": 500}
# A segment may cross a normal exchange/session close for research purposes,
# but never a short unexplained hole.  Broker epochs are not claimed to be
# verified UTC; these thresholds use only elapsed duration.
MIN_SESSION_BREAK_SECONDS = {"M5": 7_200, "M15": 14_400, "H1": 28_800}
OUTPUT = ROOT / "artifacts" / "mt5_model_eligibility.json"


def contiguous_segments(frame, timeframe: str) -> list[tuple[int, int]]:
    epochs = [int(value) for value in frame["time"]]
    if not epochs:
        return []
    segments: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(epochs)):
        if epochs[index] - epochs[index - 1] != SECONDS[timeframe]:
            segments.append((start, index))
            start = index
    segments.append((start, len(epochs)))
    return segments


def classify_gaps(frame, timeframe: str) -> dict[str, list[dict[str, int]]]:
    """Separate normal-length session boundaries from unexplained short holes.

    This is deliberately duration based, not a claim about a broker timezone
    or a particular exchange calendar.  A long closure remains visible in the
    report; it may be stitched only for chronological research, never for a
    live feed or execution decision.
    """
    expected: list[dict[str, int]] = []
    unexpected: list[dict[str, int]] = []
    epochs = [int(value) for value in frame["time"]]
    for index in range(1, len(epochs)):
        delta = epochs[index] - epochs[index - 1]
        if delta == SECONDS[timeframe]:
            continue
        gap = {"previous_epoch": epochs[index - 1], "next_epoch": epochs[index], "delta_seconds": delta}
        (expected if delta >= MIN_SESSION_BREAK_SECONDS[timeframe] else unexpected).append(gap)
    return {"session_boundaries": expected, "unexpected_gaps": unexpected}


def research_segments(frame, timeframe: str) -> list[tuple[int, int]]:
    """Segments broken only by short, unexplained gaps (not session closes)."""
    epochs = [int(value) for value in frame["time"]]
    if not epochs:
        return []
    segments: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(epochs)):
        delta = epochs[index] - epochs[index - 1]
        if delta != SECONDS[timeframe] and delta < MIN_SESSION_BREAK_SECONDS[timeframe]:
            segments.append((start, index))
            start = index
    segments.append((start, len(epochs)))
    return segments


def assess_series(asset: str, timeframe: str) -> dict[str, Any]:
    frame, gaps, metadata = load_mt5_history(asset, timeframe)
    strict_segments = contiguous_segments(frame, timeframe)
    segments = research_segments(frame, timeframe)
    lengths = [end - start for start, end in segments]
    gap_classes = classify_gaps(frame, timeframe)
    reasons: list[str] = []
    if len(frame) < MIN_ROWS[timeframe]:
        reasons.append(f"insufficient_rows:{len(frame)}<{MIN_ROWS[timeframe]}")
    if max(lengths, default=0) < MIN_CONTIGUOUS_ROWS[timeframe]:
        reasons.append(f"insufficient_contiguous_window:{max(lengths, default=0)}<{MIN_CONTIGUOUS_ROWS[timeframe]}")
    if gap_classes["unexpected_gaps"]:
        reasons.append(f"unexpected_short_gaps:{len(gap_classes['unexpected_gaps'])}")
    # A source checksum is mandatory so that a future result can be tied to the
    # exact market history it used.
    if not metadata.get("source_sha256"):
        reasons.append("missing_source_hash")
    return {
        "asset": asset.upper(), "timeframe": timeframe.upper(), "status": "ELIGIBLE_FOR_RESEARCH" if not reasons else "BLOCKED",
        "reasons": reasons, "rows": len(frame), "gap_count": len(gaps), "strict_segments": len(strict_segments),
        "research_segments": len(segments), "session_boundary_count": len(gap_classes["session_boundaries"]),
        "unexpected_short_gap_count": len(gap_classes["unexpected_gaps"]),
        "largest_research_window_rows": max(lengths, default=0), "source_sha256": metadata.get("source_sha256"),
        "timestamp_semantics": metadata["timestamp_semantics"], "execution_authorized": False,
    }


def assess_all() -> dict[str, Any]:
    manifest = json.loads((HISTORY / "manifest.json").read_text(encoding="utf-8"))
    records = [assess_series(item["asset"], item["timeframe"]) for item in manifest.get("datasets", []) if item["timeframe"] in MIN_ROWS]
    return {"generated_utc": datetime.now(timezone.utc).isoformat(), "mode": "RESEARCH_ELIGIBILITY_ONLY", "execution_authorized": False, "records": records}


def write_assessment() -> Path:
    result = assess_all(); OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return OUTPUT


if __name__ == "__main__":
    print(write_assessment())

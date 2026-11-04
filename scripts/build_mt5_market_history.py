"""Merge immutable read-only MT5 captures into canonical per-asset history.

Gaps are retained as facts in the manifest.  No candle is invented and the
result is data provenance for research/shadow, never a live execution feed.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURES = ROOT / "data" / "mt5_market"
HISTORY = CAPTURES / "history"
COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]


def build_history() -> Path:
    datasets: dict[tuple[str, str], dict[int, dict[str, str]]] = defaultdict(dict)
    sources: dict[tuple[str, str], list[str]] = defaultdict(list)
    summaries = list(CAPTURES.glob("capture_*/summary.json")) + list(CAPTURES.glob("backfill_h1_*/summary.json"))
    for summary_path in sorted(summaries):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for item in summary.get("datasets", []):
            if item.get("status") != "AVAILABLE_CLOSED_HISTORY":
                continue
            asset, tf, filename = item["asset"], item["timeframe"], item["path"]
            csv_path = summary_path.parent / filename
            if not csv_path.is_file():
                raise ValueError(f"capture references missing csv: {csv_path}")
            key = (asset, tf)
            sources[key].append(str(summary_path.parent.name))
            with csv_path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    epoch = int(row["time"])
                    existing = datasets[key].get(epoch)
                    if existing is not None and existing != row:
                        raise ValueError(f"conflicting MT5 bars for {asset} {tf} at {epoch}")
                    datasets[key][epoch] = row

    HISTORY.mkdir(parents=True, exist_ok=True)
    manifest = {"generated_utc": datetime.now(timezone.utc).isoformat(), "source": "immutable_mt5_captures", "datasets": []}
    for (asset, tf), by_epoch in sorted(datasets.items()):
        rows = [by_epoch[epoch] for epoch in sorted(by_epoch)]
        path = HISTORY / f"{asset}_{tf}.csv"
        temp = path.with_suffix(".tmp")
        with temp.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader(); writer.writerows(rows)
        temp.replace(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["datasets"].append({"asset": asset, "timeframe": tf, "rows": len(rows), "first_epoch": int(rows[0]["time"]), "last_epoch": int(rows[-1]["time"]), "sha256": digest, "sources": sorted(set(sources[(asset, tf)])), "path": path.name})
    manifest_path = HISTORY / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


if __name__ == "__main__":
    print(build_history())

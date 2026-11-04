"""Incrementally refresh the read-only MT5 research history.

Default behavior is one bounded cycle.  ``--watch`` is an explicit opt-in for
continuous collection and still never imports order/position APIs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_mt5_market_history import HISTORY, build_history
from scripts.collect_mt5_market_data import collect


def _last_epochs() -> dict[tuple[str, str], int]:
    manifest = HISTORY / "manifest.json"
    if not manifest.is_file():
        return {}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return {
        (str(item["asset"]), str(item["timeframe"])): int(item["last_epoch"])
        for item in data.get("datasets", [])
    }


def update_once(timeframes: list[str], count: int) -> dict[str, int | str]:
    before = _last_epochs()
    capture = collect(timeframes, count)
    manifest = build_history()
    after = _last_epochs()
    advanced = sum(1 for key, epoch in after.items() if epoch > before.get(key, 0))
    return {
        "capture": str(capture),
        "history_manifest": str(manifest),
        "series_advanced": advanced,
        "series_total": len(after),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframes", nargs="+", default=["M5", "H1"])
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--watch", action="store_true", help="repeat explicitly; default is one safe cycle")
    parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.interval_seconds < 60:
        parser.error("--interval-seconds must be at least 60")
    while True:
        result = update_once(args.timeframes, args.count)
        print(json.dumps(result, ensure_ascii=False))
        if not args.watch:
            return 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

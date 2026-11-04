"""Read-only scheduled collector: M5 FX/metals every 5m, all assets H1 hourly."""
from __future__ import annotations
import argparse, json, time
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.build_mt5_market_history import build_history
from scripts.collect_mt5_market_data import collect
from scripts.mt5_project_universe import project_assets

def _capture_report(path: Path) -> dict:
    """Return a compact, structured report without interpreting gaps as errors."""
    datasets = json.loads((path / "summary.json").read_text(encoding="utf-8"))["datasets"]
    unavailable = [item["asset"] for item in datasets if item["status"] == "UNAVAILABLE"]
    return {
        "capture": path.name,
        "datasets": len(datasets),
        "available": sum(item["status"] == "AVAILABLE_CLOSED_HISTORY" for item in datasets),
        "unavailable": unavailable,
    }


def run_cycle(include_h1: bool) -> dict:
    """Run one read-only collection cycle and return its provenance report."""
    assets = project_assets()
    fast = [a for a in assets if a.get("asset_class") in ("forex", "metal")]
    reports = [_capture_report(collect(["M5"], 300, fast))]
    if include_h1:
        reports.append(_capture_report(collect(["H1"], 300, assets)))
    build_history()
    return {
        "event": "mt5_market_collection_completed",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "trading_enabled": False,
        "reports": reports,
    }

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--once',action='store_true'); args=p.parse_args(); next_h1=0.0
    while True:
        now=time.time(); include_h1 = now >= next_h1
        print(json.dumps(run_cycle(include_h1), ensure_ascii=False, sort_keys=True))
        if include_h1: next_h1=now+3600
        if args.once: break
        time.sleep(300)

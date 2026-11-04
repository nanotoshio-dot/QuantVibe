"""Configured market-data universe; independent from the eight-asset risk limit."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ALIASES={"NVDA":"NVIDIA","V":"VISA","GOOGL":"GOOGL.24H","AMZN":"AMZNUSD","XOM":"XOM.24H"}

def project_assets():
    policy=json.loads((ROOT/'config'/'mt5_multiasset_risk.json').read_text(encoding='utf-8'))
    found={str(a['instrument']).upper():dict(a) for a in policy['assets']}
    # Include the explicit experiment universe, but exclude historical backups.
    for path in (ROOT/'config').glob('pipeline*.json'):
        if 'backup' in path.name or 'before_' in path.name: continue
        data=json.loads(path.read_text(encoding='utf-8'))
        for symbol in data.get('universe',[]):
            key=str(symbol).upper(); found.setdefault(key,{'instrument':key,'broker_symbol':ALIASES.get(key,key),'asset_class':'configured_market_data'})
    return [found[key] for key in sorted(found)]

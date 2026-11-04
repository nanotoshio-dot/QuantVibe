"""One-time, read-only H1 backfill from MT5 into immutable QuantVibe captures."""
from __future__ import annotations
import csv, hashlib, json, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.collect_mt5_market_data import EXPECTED_SERVER, OUTPUT_ROOT, TERMINAL, _assets, validate_closed_bars
from scripts.mt5_symbol_resolver import resolve_mt5_symbol

def main():
    import MetaTrader5 as mt5
    start=datetime(2024,1,1,tzinfo=timezone.utc); end=datetime(2026,11,4,tzinfo=timezone.utc)
    if not mt5.initialize(path=str(TERMINAL),timeout=10000): raise SystemExit(f'MT5 init failed: {mt5.last_error()}')
    try:
        account=mt5.account_info()
        if account is None or str(account.server)!=EXPECTED_SERVER: raise RuntimeError('unexpected MT5 identity')
        folder=OUTPUT_ROOT/('backfill_h1_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid.uuid4().hex[:8]); folder.mkdir(parents=True)
        summary={'source':'mt5_read_only_backfill','from':'2024-01-01','to':'2026-11-04','timeframe':'H1','trading_enabled':False,'datasets':[]}
        for asset in _assets():
            logical=asset['instrument'].upper(); symbol=resolve_mt5_symbol(mt5,asset.get('broker_symbol') or logical,cent_account=str(account.currency).upper()=='USC')
            rates=None if not symbol else mt5.copy_rates_range(symbol,mt5.TIMEFRAME_H1,start,end)
            if rates is None or len(rates)==0:
                summary['datasets'].append({'asset':logical,'symbol':symbol,'status':'UNAVAILABLE'}); continue
            # All bars ending before the requested endpoint are historical closed bars.
            rows,gaps=validate_closed_bars(rates,'H1',int(rates[-1]['time'])+3600)
            path=folder/f'{logical}_H1.csv'; cols=['time','open','high','low','close','tick_volume','spread','real_volume']
            with path.open('x',newline='',encoding='utf-8') as fh:
                writer=csv.DictWriter(fh,fieldnames=cols,extrasaction='ignore'); writer.writeheader(); writer.writerows(rows)
            summary['datasets'].append({'asset':logical,'symbol':symbol,'timeframe':'H1','status':'AVAILABLE_CLOSED_HISTORY','rows':len(rows),'gap_count':len(gaps),'gaps':gaps,'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        (folder/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8'); print(folder)
    finally: mt5.shutdown()
if __name__=='__main__': main()

"""Research-only diagnostics on existing real data. Never exports signals or trades."""
import copy
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qlib_side.common import load_config, normalize_predictions
from qlib_side.train_model import build_qlib_dataset
from qlib_side.evaluate import evaluate_predictions

def stats(frame):
    a = frame.to_numpy(dtype=float)
    finite = a[np.isfinite(a)]
    var = frame.replace([np.inf, -np.inf], np.nan).var()
    daily = frame.groupby(level='datetime').var().mean(axis=1)
    return dict(rows=len(frame), columns=frame.shape[1], nan_rate=float(np.isnan(a).mean()),
                inf_rate=float(np.isinf(a).mean()), mean=float(finite.mean()), std=float(finite.std()),
                min=float(finite.min()), max=float(finite.max()),
                quantiles=dict(zip(['0','1','5','25','50','75','95','99','100'], np.quantile(finite,[0,.01,.05,.25,.5,.75,.95,.99,1]).tolist())),
                all_missing=[str(c) for c in frame if frame[c].isna().all()],
                constant=[str(c) for c in var.index[var == 0]],
                near_constant=[str(c) for c in var.index[(var > 0) & (var <= 1e-12)]],
                feature_variance={str(k):float(v) for k,v in var.items()},
                daily_variance_summary=daily.describe().to_dict(),
                low_variance_dates=[str(d) for d in daily.index[daily <= 1e-12]])

def main():
    import qlib, lightgbm
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.data.dataset.handler import DataHandlerLP
    cfg=load_config()
    manifest=json.loads((Path(cfg['data']['raw_dir'])/'manifest.json').read_text())
    if any(manifest['symbols'].get(s,{}).get('source') != 'yfinance' for s in cfg['universe']):
        raise RuntimeError('Only existing real yfinance data is permitted')
    out=ROOT/'artifacts'/'qlib_diagnostics';out.mkdir(exist_ok=True)
    report={'versions':{'qlib':qlib.__version__,'lightgbm':lightgbm.__version__},'config':cfg,
            'raw_sha256':{s:hashlib.sha256((Path(cfg['data']['raw_dir'])/f'{s}.csv').read_bytes()).hexdigest() for s in cfg['universe']}}
    dataset=build_qlib_dataset(cfg)
    report['purged_segments']=dataset.segments
    report['matrices']={}
    for segment in ('train','valid','test'):
        report['matrices'][segment]={}
        for key in (DataHandlerLP.DK_I,DataHandlerLP.DK_L):
            frame=dataset.prepare(segment,col_set=['feature','label'],data_key=key)
            report['matrices'][segment][key]={g:stats(frame[g]) for g in ('feature','label')}
    # Both experiments use identical purged boundaries; selection never uses test IC.
    report['experiments']={}
    for mode in ('raw_label','alpha158_default'):
        if mode == 'raw_label':
            rawcfg=copy.deepcopy(cfg)
            rawcfg['training']['handler_kwargs']['learn_processors']=['DropnaLabel']
            ds=build_qlib_dataset(rawcfg)
        else:
            ds=dataset
        model=LGBModel(**cfg['training']['lgbm_kwargs'])
        history={};model.fit(ds,evals_result=history)
        result={'best_iteration':model.model.best_iteration,'best_score':model.model.best_score,'history':history}
        for segment in ('train','valid'):
            pred=model.predict(ds,segment=segment)
            result[segment+'_predictions']=stats(pred.to_frame('score'))
            result[segment+'_evaluation']=evaluate_predictions(normalize_predictions(pred),Path(cfg['data']['raw_dir']),cfg['evaluation'],cfg['signals']['top_k'])
        if mode == 'alpha158_default':
            pred=model.predict(ds)
            result['test_predictions']=stats(pred.to_frame('score'))
            result['test_evaluation']=evaluate_predictions(normalize_predictions(pred),Path(cfg['data']['raw_dir']),cfg['evaluation'],cfg['signals']['top_k'])
        report['experiments'][mode]=result
        (out/'diagnostic.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
        print(mode, json.dumps({k:v for k,v in result.items() if k in ('best_iteration','best_score','test_evaluation','valid_evaluation')}),flush=True)

if __name__ == '__main__':
    main()

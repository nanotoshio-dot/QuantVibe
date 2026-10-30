
from pathlib import Path
import numpy as np
import pandas as pd

from qlib.data.dataset.handler import DataHandlerLP
from qlib.utils import init_instance_by_config

from qlib_side.common import load_config
from qlib_side.train_model import build_qlib_dataset, normalize_predictions
from qlib_side.evaluate import evaluate_predictions


def spearman_ic(scores, labels):
    df = pd.DataFrame({
        "score": scores,
        "label": labels,
    })

    vals = []

    for _, g in df.groupby(level="datetime"):
        g = g.dropna()

        if len(g) < 4:
            continue

        if g["score"].std() == 0 or g["label"].std() == 0:
            continue

        ic = g["score"].corr(g["label"], method="spearman")

        if np.isfinite(ic):
            vals.append(ic)

    a = np.asarray(vals, dtype=float)

    mean_ic = float(a.mean()) if len(a) else float("nan")
    std_ic = float(a.std(ddof=1)) if len(a) > 1 else float("nan")
    icir = mean_ic / std_ic if np.isfinite(std_ic) and std_ic > 0 else float("nan")

    return len(a), mean_ic, icir


def main():
    cfg = load_config(None)

    print("Building SAME dataset used by pipeline...")
    dataset = build_qlib_dataset(cfg)

    model = init_instance_by_config({
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": dict(cfg["training"].get("lgbm_kwargs", {})),
    })

    history = {}

    print("Training EXACTLY like pipeline...")
    model.fit(dataset, evals_result=history)

    print()
    print("BEST ITERATION:", model.model.best_iteration)

    # Same prediction path used by pipeline
    raw_pred = model.predict(dataset)
    pred_df = normalize_predictions(raw_pred)

    # Qlib RAW test label
    y = dataset.prepare(
        "test",
        col_set="label",
        data_key=DataHandlerLP.DK_R,
    )

    if isinstance(y, pd.DataFrame):
        y = y.iloc[:, 0]

    # Align prediction Series and raw labels by exact Qlib index
    pred_series = raw_pred.rename("score")

    idx = pred_series.index.intersection(y.index)

    pred_series = pred_series.loc[idx]
    y = y.loc[idx]

    days, direct_ic, direct_icir = spearman_ic(
        pred_series,
        y,
    )

    print()
    print("DIRECT QLIB LABEL EVALUATION")
    print("days :", days)
    print("IC   :", direct_ic)
    print("ICIR :", direct_icir)

    print()
    print("RUNNING THE ACTUAL QUANTVIBE EVALUATOR ON THE SAME PREDICTIONS...")

    report = evaluate_predictions(
        predictions=pred_df,
        raw_dir=Path(cfg["data"]["raw_dir"]),
        cfg_eval=cfg["evaluation"],
        top_k=int(cfg["signals"]["top_k"]),
    )

    print()
    print("QUANTVIBE EVALUATOR RESULT")

    metrics = report.get("metrics", report)

    for key in [
        "n_days",
        "mean_ic",
        "icir",
        "hit_rate_topk",
        "avg_topk_fwd_return",
        "avg_universe_fwd_return",
    ]:
        if key in metrics:
            print(f"{key}: {metrics[key]}")

    print()
    print("=" * 60)
    print("DECISION")
    print("=" * 60)

    gate_ic = metrics.get("mean_ic")
    gate_icir = metrics.get("icir")

    print("same_run_best_iteration =", model.model.best_iteration)
    print("direct_qlib_ic          =", direct_ic)
    print("evaluator_ic            =", gate_ic)
    print("direct_qlib_icir        =", direct_icir)
    print("evaluator_icir          =", gate_icir)

    if gate_ic is not None and np.isfinite(gate_ic):
        diff = abs(float(direct_ic) - float(gate_ic))
        print("absolute_ic_difference  =", diff)

        if diff < 0.005:
            print("VERDICT: evaluator and Qlib AGREE.")
        else:
            print("VERDICT: evaluator and Qlib DISAGREE -> real alignment/evaluation bug.")


if __name__ == "__main__":
    main()


import numpy as np
import pandas as pd

from qlib.data.dataset.handler import DataHandlerLP
from qlib.utils import init_instance_by_config

from qlib_side.common import load_config
from qlib_side.train_model import build_qlib_dataset


def main():
    cfg = load_config(None)
    dataset = build_qlib_dataset(cfg)

    model = init_instance_by_config({
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": dict(cfg["training"].get("lgbm_kwargs", {})),
    })

    history = {}

    print("Training 100 trees for VALIDATION IC diagnostic...")

    model.fit(
        dataset,
        num_boost_round=100,
        early_stopping_rounds=1000,
        verbose_eval=0,
        evals_result=history,
    )

    booster = model.model

    x = dataset.prepare(
        "valid",
        col_set="feature",
        data_key=DataHandlerLP.DK_I,
    )

    y = dataset.prepare(
        "valid",
        col_set="label",
        data_key=DataHandlerLP.DK_L,
    )

    if isinstance(y, pd.DataFrame):
        y = y.iloc[:, 0]

    idx = x.index.intersection(y.index)
    x = x.loc[idx]
    y = y.loc[idx]

    def calc_ic(pred):
        frame = pd.DataFrame(
            {"score": pred, "label": y.to_numpy()},
            index=idx,
        )

        ics = []

        for _, g in frame.groupby(level="datetime"):
            g = g.dropna()

            if len(g) < 4:
                continue

            if g["score"].std() == 0 or g["label"].std() == 0:
                continue

            ic = g["score"].corr(g["label"], method="spearman")

            if np.isfinite(ic):
                ics.append(ic)

        a = np.asarray(ics, dtype=float)

        mean_ic = float(a.mean()) if len(a) else np.nan
        std_ic = float(a.std(ddof=1)) if len(a) > 1 else np.nan
        icir = mean_ic / std_ic if np.isfinite(std_ic) and std_ic > 0 else np.nan

        return mean_ic, icir, len(a)

    results = []

    for n in range(1, 101):
        pred = booster.predict(x.values, num_iteration=n)
        mean_ic, icir, days = calc_ic(pred)

        results.append({
            "trees": n,
            "mean_ic": mean_ic,
            "icir": icir,
            "days": days,
        })

    res = pd.DataFrame(results)

    valid_name = next(
        (name for name in history if "valid" in name.lower()),
        list(history.keys())[-1],
    )

    metric_name = next(iter(history[valid_name]))
    values = np.asarray(history[valid_name][metric_name], dtype=float)

    best_l2 = int(values.argmin()) + 1
    best_ic = res.loc[res["mean_ic"].idxmax()]
    best_icir = res.loc[res["icir"].idxmax()]

    print()
    print("VALIDATION IC CURVE - TREES 1 TO 30")
    print(res.loc[res["trees"].between(1, 30)].to_string(index=False))

    print()
    print("OUT-OF-SAMPLE TEST CHECK")
    print("IMPORTANT: iterations were selected WITHOUT looking at test.")

    x_test = dataset.prepare(
        "test",
        col_set="feature",
        data_key=DataHandlerLP.DK_I,
    )

    y_test = dataset.prepare(
        "test",
        col_set="label",
        data_key=DataHandlerLP.DK_R,
    )

    if isinstance(y_test, pd.DataFrame):
        y_test = y_test.iloc[:, 0]

    test_idx = x_test.index.intersection(y_test.index)
    x_test = x_test.loc[test_idx]
    y_test = y_test.loc[test_idx]

    def test_ic(num_trees):
        pred = booster.predict(x_test.values, num_iteration=num_trees)

        frame = pd.DataFrame(
            {"score": pred, "label": y_test.to_numpy()},
            index=test_idx,
        )

        ics = []

        for _, g in frame.groupby(level="datetime"):
            g = g.dropna()

            if len(g) < 4:
                continue

            if g["score"].std() == 0 or g["label"].std() == 0:
                continue

            ic = g["score"].corr(g["label"], method="spearman")

            if np.isfinite(ic):
                ics.append(ic)

        a = np.asarray(ics, dtype=float)

        mean_ic = float(a.mean()) if len(a) else np.nan
        std_ic = float(a.std(ddof=1)) if len(a) > 1 else np.nan
        icir = mean_ic / std_ic if np.isfinite(std_ic) and std_ic > 0 else np.nan

        return len(a), mean_ic, icir

    for trees in [11, 27, 57]:
        days, mic, mir = test_ic(trees)
        print(
            f"trees={trees:>2} | days={days} | "
            f"IC={mic:+.6f} | ICIR={mir:+.6f}"
        )

    print()
    print("SUMMARY")
    print("Best validation L2 iteration :", best_l2)
    print(
        "Best validation IC iteration :",
        int(best_ic["trees"]),
        "IC=",
        round(float(best_ic["mean_ic"]), 6),
        "ICIR=",
        round(float(best_ic["icir"]), 6),
    )
    print(
        "Best validation ICIR iteration:",
        int(best_icir["trees"]),
        "IC=",
        round(float(best_icir["mean_ic"]), 6),
        "ICIR=",
        round(float(best_icir["icir"]), 6),
    )


if __name__ == "__main__":
    main()

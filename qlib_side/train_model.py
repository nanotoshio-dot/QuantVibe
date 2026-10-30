from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from qlib_side.common import fail, load_config, normalize_predictions

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"


def _demo_momentum(cfg) -> "object":
    import pandas as pd

    window = int(cfg["training"].get("momentum_window", 20))
    raw_dir = Path(cfg["data"]["raw_dir"])
    frames = []
    for symbol in cfg["universe"]:
        csv_path = raw_dir / f"{symbol}.csv"
        if not csv_path.is_file():
            continue
        df = pd.read_csv(csv_path).sort_values("date")
        if len(df) <= window:
            continue
        close = df["close"].astype(float).reset_index(drop=True)
        score = close / close.shift(window) - 1.0
        frame = pd.DataFrame(
            {"datetime": df["date"], "instrument": symbol, "score": score}
        ).dropna()
        frames.append(frame)
    if not frames:
        fail("no se encontraron datos crudos para el modo demo; ejecuta qlib_side.prepare_data primero")
    return normalize_predictions(pd.concat(frames, ignore_index=True))


def build_qlib_dataset(cfg):
    import qlib
    from qlib.constant import REG_CN, REG_US
    from qlib.utils import init_instance_by_config

    region = REG_US if str(cfg.get("region", "us")).lower() == "us" else REG_CN
    qlib.init(provider_uri=cfg["data"]["qlib_dir"], region=region)

    segments = {name: tuple(bounds) for name, bounds in cfg["training"]["segments"].items()}
    # The configured label requires prices two trading sessions after each feature date.
    # Purge boundary observations so training/validation outcomes precede the next segment.
    if cfg["training"]["label"].replace(" ", "") != "Ref($close,-2)/Ref($close,-1)-1":
        raise ValueError("Label lookahead must be reviewed before using a different label")
    import pandas as pd
    calendar = pd.DatetimeIndex(pd.read_csv(
        Path(cfg["data"]["qlib_dir"]) / "calendars" / "day.txt", header=None
    )[0])
    for name, following in (("train", "valid"), ("valid", "test")):
        eligible = calendar[calendar < pd.Timestamp(segments[following][0])]
        if len(eligible) < 3:
            raise ValueError("Insufficient calendar for label boundary purge")
        segments[name] = (segments[name][0], min(segments[name][1], eligible[-3].strftime("%Y-%m-%d")))
    handler_kwargs = dict(cfg["training"].get("handler_kwargs", {}))
    handler_config = {
        "class": "Alpha158",
        "module_path": "qlib.contrib.data.handler",
        "kwargs": {
            "infer_processors": [
                {
                    "class": "RobustZScoreNorm",
                    "kwargs": {
                        "fields_group": "feature",
                        "clip_outlier": True
                    }
                },
                {
                    "class": "Fillna",
                    "kwargs": {
                        "fields_group": "feature"
                    }
                }
            ],
            "learn_processors": [
                {"class": "DropnaLabel"},
                {"class": "CSRankNorm", "kwargs": {"fields_group": "label"}},
            ],
            **handler_kwargs,
            "instruments": list(cfg["universe"]),
            "start_time": segments["train"][0],
            "end_time": segments["test"][1],
            "fit_start_time": segments["train"][0],
            "fit_end_time": segments["train"][1],
            "label": [cfg["training"]["label"]],
            # Explicit preprocessing for the ranking workflow:
            # RobustZScoreNorm + Fillna for features; DropnaLabel + CSRankNorm for labels.
        },
    }
    dataset_config = {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {"handler": handler_config, "segments": segments},
    }
    return init_instance_by_config(dataset_config)


def _train_qlib(cfg) -> "object":
    import json
    from qlib.utils import init_instance_by_config

    dataset = build_qlib_dataset(cfg)

    model_name = str(
        cfg["training"].get("model", "linear")
    ).lower()

    history = {}

    if model_name in ("linear", "ridge"):
        kwargs = dict(
            cfg["training"].get(
                "linear_kwargs",
                {
                    "estimator": "ridge",
                    "alpha": 0.05,
                },
            )
        )

        model_config = {
            "class": "LinearModel",
            "module_path": "qlib.contrib.model.linear",
            "kwargs": kwargs,
        }

        model = init_instance_by_config(model_config)
        model.fit(dataset)

        model_label = "LinearModel"

        metrics_payload = {
            "model": model_label,
            "model_kwargs": kwargs,
            "segments": dataset.segments,
        }

    elif model_name in ("lgbm", "lightgbm"):
        kwargs = dict(
            cfg["training"].get("lgbm_kwargs", {})
        )

        model_config = {
            "class": "LGBModel",
            "module_path": "qlib.contrib.model.gbdt",
            "kwargs": kwargs,
        }

        model = init_instance_by_config(model_config)

        model.fit(
            dataset,
            evals_result=history,
        )

        model_label = "LGBModel"

        metrics_payload = {
            "model": model_label,
            "best_iteration": getattr(
                model.model,
                "best_iteration",
                None,
            ),
            "best_score": getattr(
                model.model,
                "best_score",
                None,
            ),
            "segments": dataset.segments,
            "history": history,
        }

    else:
        raise RuntimeError(
            f"Unsupported training model: {model_name}"
        )

    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    (
        ARTIFACTS / "training_metrics.json"
    ).write_text(
        json.dumps(
            metrics_payload,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    pred = model.predict(dataset)

    return normalize_predictions(pred)

def train(config_path: str | None = None, force_demo: bool | None = None):
    import pandas as pd

    cfg = load_config(config_path)
    demo_env = os.environ.get("QVB_FORCE_DEMO", "").strip() == "1"
    demo = force_demo if force_demo is not None else demo_env

    configured_model = str(cfg["training"].get("model", "linear")).lower()
    source_model = "LinearModel" if configured_model in ("linear", "ridge") else "LGBModel"
    data_source = "qlib"
    pred = None
    if not demo:
        try:
            import qlib  # noqa: F401

            print(f"  Qlib detectado -> entrenando {source_model}")
            pred = _train_qlib(cfg)
        except ImportError:
            raise RuntimeError("Real training requires pyqlib; demo must be explicitly requested")
        except Exception as exc:
            raise RuntimeError("Real Qlib training failed; no demo fallback") from exc
    if pred is None:
        source_model = "DemoMomentum"
        manifest_path = Path(cfg["data"]["raw_dir"]) / "manifest.json"
        if manifest_path.is_file():
            with open(manifest_path, "r", encoding="utf-8") as fh:
                sources = {v.get("source") for v in json.load(fh)["symbols"].values()}
            data_source = sources.pop() if len(sources) == 1 else "mixed"
        else:
            data_source = "unknown"
        pred = _demo_momentum(cfg)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out_csv = ARTIFACTS / "predictions.csv"
    assert isinstance(pred, pd.DataFrame)
    pred.to_csv(out_csv, index=False)

    meta_path = ARTIFACTS / "predictions.meta.json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "source_model": source_model,
                "data_source": data_source,
                "rows": int(len(pred)),
                "as_of": str(pred["datetime"].max()),
                "test_window": list(cfg["training"]["segments"]["test"]),
            },
            fh,
            indent=2,
        )
    print(f"  predicciones escritas: {out_csv} filas={len(pred)} modelo={source_model}")
    return out_csv


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Entrena el modelo de señales (Qlib o fallback demo)")
    parser.add_argument("--config", default=None)
    parser.add_argument("--force-demo", action="store_true")
    args = parser.parse_args()
    try:
        train(args.config, args.force_demo or None)
    except SystemExit:
        raise
    except Exception as exc:
        fail(f"train_model falló: {exc}")

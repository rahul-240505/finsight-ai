"""Train, evaluate and (optionally) register the Isolation Forest risk model.

Run from backend/ (uses the app's feature code, so training and serving match):

    PYTHONPATH=. uv run python ../ml/training/train_isolation_forest.py \
        --csv ../data/transactions_500k.csv --labels ../data/labels_500k.csv --register

Time-based split (no shuffling, no peeking at the future):
    train      2025-01-01 .. 2025-09-30   fit the model (labels never used)
    validation 2025-10-01 .. 2025-11-30   choose the score threshold (max F1)
    test       2025-12-01 .. 2025-12-31   report once, nothing tuned here

Four scorers are evaluated the same way: random scores, a one-feature rule (amount_z), the
Isolation Forest alone, and a hybrid (the larger of the forest and amount_z percentiles; see
app/modules/ml/model.py). The served model is chosen by *validation* PR-AUC, never by test.
The labels are the generator's injected anomalies, used only for evaluation.
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from app.db.models import ModelVersion
from app.db.session import get_sessionmaker
from app.modules.ml import registry
from app.modules.ml.evaluation import (
    bootstrap_pr_auc,
    choose_threshold,
    metrics_at,
    precision_at_k,
)
from app.modules.ml.features import FEATURE_NAMES, build_features
from app.modules.ml.model import RiskModel

VAL_START = pd.Timestamp("2025-10-01", tz="UTC")
TEST_START = pd.Timestamp("2025-12-01", tz="UTC")
PARAMS = {"n_estimators": 200, "max_samples": 256, "random_state": 42, "n_jobs": -1}


def load(csv: Path, labels: Path) -> tuple[pd.DataFrame, np.ndarray, pd.Series]:
    df = pd.read_csv(csv, dtype={"transaction_id": str, "account_id": str})
    df["occurred_at"] = pd.to_datetime(df["timestamp"], utc=True)
    lab = pd.read_csv(labels, dtype=str).set_index("transaction_id")["anomaly_type"]
    kind = df["transaction_id"].map(lab).fillna("normal")
    return df, (kind != "normal").to_numpy().astype(int), kind


def evaluate(name: str, scores: np.ndarray, y: np.ndarray, kind: pd.Series, split: dict) -> dict:
    threshold = choose_threshold(y[split["val"]], scores[split["val"]])
    test = split["test"]
    result = {
        "threshold": round(threshold, 6),
        "validation": metrics_at(y[split["val"]], scores[split["val"]], threshold),
        "test": metrics_at(y[test], scores[test], threshold),
    }
    for part in ("validation", "test"):
        mask = split["val" if part == "validation" else "test"]
        k = max(1, int(0.01 * mask.sum()))  # review budget: top 1% of rows
        result[part]["precision_at_top_1pct"] = precision_at_k(y[mask], scores[mask], k)
        flagged = scores[mask] >= threshold
        result[part]["recall_by_type"] = {
            t: round(float(flagged[(kind[mask] == t).to_numpy()].mean()), 4)
            for t in sorted(kind[mask].unique())
            if t != "normal"
        }
    result["test"]["pr_auc_95ci"] = bootstrap_pr_auc(y[test], scores[test])["a"]
    v, t = result["validation"], result["test"]
    print(f"{name:18} VALIDATION PR-AUC {v['pr_auc']:.4f}  recall by type {v['recall_by_type']}")
    print(
        f"{name:18} test PR-AUC {t['pr_auc']:.4f}  ROC-AUC {t['roc_auc']:.4f}  "
        f"P {t['precision']:.3f}  R {t['recall']:.3f}  F1 {t['f1']:.3f}  "
        f"P@1% {t['precision_at_top_1pct']:.3f}  flag rate {t['flag_rate']:.4f}  "
        f"PR-AUC 95% CI {t['pr_auc_95ci']}"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--register", action="store_true", help="save and activate the model")
    args = parser.parse_args()

    df, y, kind = load(args.csv, args.labels)
    started = time.perf_counter()
    X = build_features(df)
    feature_secs = time.perf_counter() - started
    t = df["occurred_at"]
    split = {
        "train": (t < VAL_START).to_numpy(),
        "val": ((t >= VAL_START) & (t < TEST_START)).to_numpy(),
        "test": (t >= TEST_START).to_numpy(),
    }
    sizes = {k: int(v.sum()) for k, v in split.items()}
    positives = {k: int(y[v].sum()) for k, v in split.items()}
    print(f"rows {len(df)}  split {sizes}  positives {positives}  features {feature_secs:.2f}s")

    started = time.perf_counter()
    forest = IsolationForest(**PARAMS).fit(X[split["train"]])  # labels never used to fit
    fit_secs = time.perf_counter() - started
    candidates = {
        "isolation_forest": RiskModel(forest, X[split["train"]], combine=False),
        "hybrid": RiskModel(forest, X[split["train"]], combine=True),
    }

    rng = np.random.default_rng(42)
    results = {
        "random": evaluate("random baseline", rng.random(len(y)), y, kind, split),
        "rule_amount_z": evaluate("rule: amount_z", X["amount_z"].to_numpy(), y, kind, split),
    }
    for name, candidate in candidates.items():
        results[name] = evaluate(name, candidate.risk_score(X), y, kind, split)
    chosen = max(candidates, key=lambda n: results[n]["validation"]["pr_auc"])
    model = candidates[chosen]
    print(f"fit {fit_secs:.2f}s on {sizes['train']} rows · chosen by validation PR-AUC: {chosen}")

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    version = f"iforest-{stamp}"
    out = registry.get_settings().model_dir / version
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "version": version,
        "data": str(args.csv.name),
        "split": {"train_end": str(VAL_START.date()), "test_start": str(TEST_START.date())},
        "sizes": sizes,
        "positives": positives,
        "params": PARAMS,
        "features": FEATURE_NAMES,
        "results": results,
        "chosen": chosen,
        "fit_seconds": round(fit_secs, 2),
    }
    (out / "metrics.json").write_text(json.dumps(report, indent=2))
    print(f"metrics → {out / 'metrics.json'}")

    if args.register:
        relative = f"{version}/model.joblib"
        sha = registry.save_model(model, relative)
        with get_sessionmaker()() as db:
            registry.register(
                db,
                ModelVersion(
                    name="isolation_forest",
                    version=version,
                    algorithm=f"IsolationForest ({chosen})",
                    feature_names=FEATURE_NAMES,
                    params={**PARAMS, "combine": model.combine},
                    metrics=results[chosen],
                    threshold=results[chosen]["threshold"],
                    training_data=(
                        f"{args.csv.name}; train < {VAL_START.date()}, "
                        f"threshold on validation < {TEST_START.date()}, test after"
                    ),
                    artifact_path=relative,
                    artifact_sha256=sha,
                ),
                activate=True,
            )
        print(f"registered and activated {version} (sha256 {sha[:12]}…)")


if __name__ == "__main__":
    main()

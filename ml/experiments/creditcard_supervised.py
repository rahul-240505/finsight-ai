"""Supervised fraud classification on the public credit-card dataset (OpenML 1597).

A separate experiment, not served by the API. It shows supervised learning on real
(anonymised) labels next to the unsupervised model trained on synthetic data.

Run from backend/:

    PYTHONPATH=. uv run python ../ml/experiments/creditcard_supervised.py

Dataset: 284,807 European card transactions over two days (2013), 492 frauds (0.17%).
Features V1..V28 are PCA components (the originals are confidential), plus Amount.

Choices:
  * Split by position: first 60% train, next 20% validation, last 20% test. OpenML's copy has
    no Time column, but keeps the original file's chronological row order, so this
    approximates a time-based split (no shuffling).
  * Scaling happens inside a Pipeline, fitted on training rows only (no leakage).
  * Threshold chosen on validation (max F1); test reported once.
"""

import json
import time
from pathlib import Path

import numpy as np
from sklearn.datasets import fetch_openml
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.modules.ml.evaluation import (
    bootstrap_pr_auc,
    choose_threshold,
    metrics_at,
    precision_at_k,
)

DATA_HOME = Path(__file__).resolve().parents[2] / "data" / "openml"
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "experiments" / "creditcard.json"


def main() -> None:
    frame = fetch_openml(data_id=1597, as_frame=True, data_home=DATA_HOME).frame
    y = (frame["Class"].astype(str) == "1").to_numpy().astype(int)
    X = frame.drop(columns=["Class"]).astype(float)

    n = len(frame)
    cut1, cut2 = int(0.6 * n), int(0.8 * n)
    parts = {"train": slice(0, cut1), "val": slice(cut1, cut2), "test": slice(cut2, n)}
    print(
        f"rows {n}  frauds {y.sum()} ({y.mean():.4%})  "
        + "  ".join(f"{k} {y[s].sum()}/{s.stop - s.start}" for k, s in parts.items())
    )

    models = {
        "logistic_regression": make_pipeline(
            StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=2000)
        ),
        "gradient_boosting": HistGradientBoostingClassifier(
            class_weight="balanced", random_state=42
        ),
    }
    results = {}
    tr, va, te = parts["train"], parts["val"], parts["test"]
    rng = np.random.default_rng(42)
    baselines = {"random": rng.random(n), "rule_amount": X["Amount"].to_numpy()}
    for name, scores in baselines.items():
        threshold = choose_threshold(y[va], scores[va])
        results[name] = {"test": metrics_at(y[te], scores[te], threshold)}
    for name, model in models.items():
        started = time.perf_counter()
        model.fit(X.iloc[tr], y[tr])
        fit_secs = round(time.perf_counter() - started, 2)
        scores = model.predict_proba(X)[:, 1]
        threshold = choose_threshold(y[va], scores[va])
        results[name] = {
            "threshold": round(threshold, 6),
            "fit_seconds": fit_secs,
            "validation": metrics_at(y[va], scores[va], threshold),
            "test": metrics_at(y[te], scores[te], threshold),
        }
        results[name]["test"]["precision_at_top_100"] = precision_at_k(y[te], scores[te], 100)
    test_scores = {name: m.predict_proba(X.iloc[te])[:, 1] for name, m in models.items()}
    lr, gb = test_scores["logistic_regression"], test_scores["gradient_boosting"]
    ci = bootstrap_pr_auc(y[te], lr, gb)
    results["logistic_regression"]["test"]["pr_auc_95ci"] = ci["a"]
    results["gradient_boosting"]["test"]["pr_auc_95ci"] = bootstrap_pr_auc(y[te], gb)["a"]
    results["gb_minus_lr_pr_auc_95ci"] = ci["b_minus_a"]
    for name, r in results.items():
        if name == "gb_minus_lr_pr_auc_95ci":
            continue
        t = r["test"]
        print(
            f"{name:20} test PR-AUC {t['pr_auc']:.4f}  ROC-AUC {t['roc_auc']:.4f}  "
            f"P {t['precision']:.3f}  R {t['recall']:.3f}  F1 {t['f1']:.3f}  "
            f"TP {t['tp']} FP {t['fp']} FN {t['fn']}"
        )
    for name in models:
        print(f"{name:20} test PR-AUC 95% CI {results[name]['test']['pr_auc_95ci']}")
    print(f"gradient boosting − logistic regression PR-AUC, 95% CI {ci['b_minus_a']}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"rows": n, "frauds": int(y.sum()), "results": results}, indent=2))
    print(f"results → {OUT}")


if __name__ == "__main__":
    main()

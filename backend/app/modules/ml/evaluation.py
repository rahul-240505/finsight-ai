"""Metrics for rare-event detection. Higher score = more unusual throughout.

Accuracy is deliberately absent: with ~1% positives, flagging nothing scores ~99% accuracy.
"""

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score


def choose_threshold(y_true: np.ndarray, scores: np.ndarray) -> float:
    """The score cut-off with the best F1 on this (validation) data.

    Chosen on validation and then frozen; the test set is only used to report the result.
    """
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    # precision/recall have one more element than thresholds (the end point); drop it.
    p, r = precision[:-1], recall[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        f1 = np.where(p + r > 0, 2 * p * r / (p + r), 0.0)
    return float(thresholds[int(np.argmax(f1))])


def metrics_at(y_true: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, float]:
    """Threshold-free (PR-AUC, ROC-AUC) and at-threshold metrics, rounded for reporting."""
    flagged = scores >= threshold
    tp = int(np.sum(flagged & (y_true == 1)))
    fp = int(np.sum(flagged & (y_true == 0)))
    fn = int(np.sum(~flagged & (y_true == 1)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "pr_auc": round(float(average_precision_score(y_true, scores)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, scores)), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "flag_rate": round(float(flagged.mean()), 4),
        "positive_rate": round(float(y_true.mean()), 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def precision_at_k(y_true: np.ndarray, scores: np.ndarray, k: int) -> float:
    """Of the k highest-scored rows (an analyst's review budget), the share that are positive."""
    top = np.argsort(-scores, kind="stable")[:k]
    return round(float(y_true[top].mean()), 4)


def bootstrap_pr_auc(
    y_true: np.ndarray, scores_a: np.ndarray, scores_b: np.ndarray | None = None, n: int = 1000
) -> dict[str, list[float]]:
    """95% bootstrap intervals for PR-AUC (and for B − A when `scores_b` is given).

    With few positives (e.g. 75 frauds), a single PR-AUC number hides a lot of luck; the
    interval shows how much. Both models are resampled on the same rows (a paired comparison).
    """
    rng = np.random.default_rng(42)
    a_vals, diffs = [], []
    size = len(y_true)
    for _ in range(n):
        idx = rng.integers(0, size, size)
        if y_true[idx].sum() == 0:
            continue
        a = average_precision_score(y_true[idx], scores_a[idx])
        a_vals.append(a)
        if scores_b is not None:
            diffs.append(average_precision_score(y_true[idx], scores_b[idx]) - a)
    result = {"a": [round(float(v), 4) for v in np.percentile(a_vals, [2.5, 97.5])]}
    if diffs:
        result["b_minus_a"] = [round(float(v), 4) for v in np.percentile(diffs, [2.5, 97.5])]
    return result

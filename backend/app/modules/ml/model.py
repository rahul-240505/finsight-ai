"""The served risk model: an Isolation Forest, optionally combined with one explicit signal.

Risk scores are percentiles of the *training* data: 0.997 means "more unusual than 99.7% of
the transactions the model was trained on". Percentiles make different signals comparable
and are easy to explain.

combine=True ("hybrid") takes the larger of two percentiles:
  - the forest's anomaly score (catches odd *combinations*: bursts, new merchant at night)
  - amount_z, the amount vs. the account's own history (catches very large single amounts,
    which the forest under-ranks when everything else about the transaction looks normal)

This class is pickled with the model file, so it must stay importable at this path.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


class RiskModel:
    def __init__(self, forest: IsolationForest, train_X: pd.DataFrame, combine: bool) -> None:
        self.forest = forest
        self.combine = combine
        self.feature_names = list(train_X.columns)
        # Sorted training distributions, used to turn raw values into percentiles.
        self._forest_ref = np.sort(self._forest_raw(train_X))
        self._z_ref = np.sort(train_X["amount_z"].to_numpy())

    def _forest_raw(self, X: pd.DataFrame) -> np.ndarray:
        return -self.forest.score_samples(X[self.feature_names])  # higher = more unusual

    @staticmethod
    def _percentile(reference: np.ndarray, values: np.ndarray) -> np.ndarray:
        """Share of training values at or below each value, interpolated so the result keeps
        increasing with the raw score. Values beyond the training maximum are squeezed into the
        gap just below 1.0 instead of all tying at 1.0, which would make the most extreme
        transactions' order arbitrary."""
        n = len(reference)
        idx = np.searchsorted(reference, values, side="right")  # count of reference <= value
        lo = reference[np.clip(idx - 1, 0, n - 1)]
        hi = reference[np.clip(idx, 0, n - 1)]
        with np.errstate(divide="ignore", invalid="ignore"):
            frac = np.where(hi > lo, (values - lo) / (hi - lo), 0.0)
        scale = float(reference.std()) or 1.0
        frac = np.where(idx >= n, 1.0 - np.exp(-(values - reference[-1]) / scale), frac)
        return (idx + np.clip(frac, 0.0, 1.0)) / (n + 1)

    def risk_score(self, X: pd.DataFrame) -> np.ndarray:
        forest = self._percentile(self._forest_ref, self._forest_raw(X))
        if not self.combine:
            return forest
        amount = self._percentile(self._z_ref, X["amount_z"].to_numpy())
        return np.maximum(forest, amount)

"""Feature engineering for transaction risk scoring.

One function, used by both training and serving, so the two can never compute features
differently (train/serve skew).

Every per-account feature looks only at that account's *earlier* transactions (an expanding
window), never at later ones. A feature that used the account's overall average would quietly
use the future, and evaluation on a time-based split would look better than reality.

Input columns: account_id, occurred_at (tz-aware), amount, merchant, category.
"""

import math

import numpy as np
import pandas as pd

FEATURE_NAMES = [
    "log_amount",  # size of the amount, log scale (currencies differ; z-score handles that)
    "amount_z",  # how many standard deviations above the account's earlier average
    "hour_sin",  # time of day on a circle, so 23:59 and 00:01 are close
    "hour_cos",
    "log_secs_since_prev",  # gap since the account's previous transaction
    "merchant_familiarity",  # share of earlier transactions at this merchant (0 = new)
    "category_familiarity",  # share of earlier transactions in this category
    "tx_last_hour",  # the account's transactions in the previous 60 minutes
]
MIN_HISTORY = 5  # below this, account-relative features are set to neutral values
NO_PREVIOUS_SECONDS = 30 * 24 * 3600.0  # gap used for an account's first transaction
Z_CLIP = 20.0


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return a float DataFrame of FEATURE_NAMES, aligned with (same index as) `df`."""
    d = pd.DataFrame(
        {
            "account_id": df["account_id"].to_numpy(),
            # Plain UTC datetime64: a tz-aware column's .to_numpy() gives slow Python objects.
            "t": pd.to_datetime(df["occurred_at"], utc=True).dt.tz_convert(None).to_numpy(),
            "amount": df["amount"].astype(float).to_numpy(),
            "merchant": df["merchant"].to_numpy(),
            "category": df["category"].to_numpy(),
            "pos": np.arange(len(df)),
        }
    )
    # Stable order: account, time, then original position for ties.
    d = d.sort_values(["account_id", "t", "pos"], kind="stable").reset_index(drop=True)
    by_account = d.groupby("account_id", sort=False)
    amount = d["amount"]
    n_prev = by_account.cumcount().to_numpy().astype(float)  # earlier transactions
    enough = n_prev >= MIN_HISTORY

    # Expanding mean/std of *earlier* amounts: cumulative sums minus the current row.
    sum_prev = by_account["amount"].cumsum().to_numpy() - amount.to_numpy()
    sq_prev = (amount**2).groupby(d["account_id"], sort=False).cumsum().to_numpy() - amount**2
    with np.errstate(divide="ignore", invalid="ignore"):
        mean_prev = np.where(n_prev > 0, sum_prev / n_prev, 0.0)
        var_prev = np.where(n_prev > 0, sq_prev / n_prev - mean_prev**2, 0.0)
        std_prev = np.sqrt(np.clip(var_prev, 0.0, None))
        z = np.where(enough & (std_prev > 0), (amount - mean_prev) / std_prev, 0.0)

    hours = (d["t"].dt.hour + d["t"].dt.minute / 60.0).to_numpy()
    gap = by_account["t"].diff().dt.total_seconds().fillna(NO_PREVIOUS_SECONDS).to_numpy()

    same_merchant = d.groupby(["account_id", "merchant"], sort=False).cumcount().to_numpy()
    same_category = d.groupby(["account_id", "category"], sort=False).cumcount().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        merchant_fam = np.where(enough, same_merchant / n_prev, 1.0)
        category_fam = np.where(enough, same_category / n_prev, 1.0)

    features = pd.DataFrame(
        {
            "log_amount": np.log1p(np.abs(amount.to_numpy())),
            "amount_z": np.clip(z, -Z_CLIP, Z_CLIP),
            "hour_sin": np.sin(2 * math.pi * hours / 24),
            "hour_cos": np.cos(2 * math.pi * hours / 24),
            "log_secs_since_prev": np.log1p(np.clip(gap, 0.0, None)),
            "merchant_familiarity": merchant_fam,
            "category_familiarity": category_fam,
            "tx_last_hour": _count_previous_hour(d),
        }
    )
    # Back to the caller's row order and index.
    features.index = d["pos"].to_numpy()
    features = features.sort_index()
    features.index = df.index
    return features[FEATURE_NAMES].astype(float)


def _count_previous_hour(d: pd.DataFrame) -> np.ndarray:
    """For each row, the same account's earlier rows within the past 3600 s.

    Rows are sorted by (account, time). A combined key `account_code * 1e10 + seconds` is
    then globally sorted, so one vectorised binary search finds each window's start without
    a Python loop over 5,000 accounts.
    """
    codes = pd.factorize(d["account_id"])[0].astype(np.int64)
    # Explicit unit: pandas 3 stores datetimes in microseconds by default (pandas 2 used
    # nanoseconds), so dividing the raw int64 by a fixed factor silently gives wrong units.
    seconds = d["t"].to_numpy().astype("datetime64[s]").astype(np.int64)
    key = codes * 10_000_000_000 + seconds
    window_start = np.searchsorted(key, key - 3600, side="left")
    return (np.arange(len(key)) - window_start).astype(float)


def explain(features: pd.Series, occurred_at: pd.Timestamp) -> list[str]:
    """Plain-language reasons for a flagged transaction, strongest first (max 3).

    These describe which inputs are unusual; they are not the model's internal reasoning.
    """
    reasons: list[tuple[float, str]] = []
    z = features["amount_z"]
    if z >= 3:
        reasons.append((z, f"Amount is {z:.1f} standard deviations above this account's average"))
    if features["merchant_familiarity"] == 0:
        reasons.append((5.0, "First transaction at this merchant for this account"))
    if features["category_familiarity"] == 0:
        reasons.append((4.0, "First transaction in this category for this account"))
    if features["tx_last_hour"] >= 3:
        n = int(features["tx_last_hour"])
        reasons.append((3.0 + n, f"{n} other transactions by this account in the previous hour"))
    hour = occurred_at.hour
    if hour < 5:
        reasons.append((3.5, f"Made at an unusual time ({occurred_at:%H:%M} UTC)"))
    if features["log_secs_since_prev"] < math.log1p(120):
        reasons.append((2.0, "Less than 2 minutes after the account's previous transaction"))
    if not reasons:
        return ["Unusual combination of amount, timing and merchant for this account"]
    return [text for _, text in sorted(reasons, key=lambda r: r[0], reverse=True)[:3]]

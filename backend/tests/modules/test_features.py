"""Feature engineering: correctness and, above all, no peeking at the future."""

import numpy as np
import pandas as pd
import pytest

from app.modules.ml.features import FEATURE_NAMES, MIN_HISTORY, build_features, explain


def frame(rows: list[tuple[str, str, float, str, str]]) -> pd.DataFrame:
    """rows: (account_id, ISO time, amount, merchant, category)."""
    df = pd.DataFrame(rows, columns=["account_id", "occurred_at", "amount", "merchant", "category"])
    df["occurred_at"] = pd.to_datetime(df["occurred_at"], utc=True)
    return df


def history(n: int, amount: float = 20.0, account: str = "A") -> list[tuple]:
    return [
        (account, f"2025-03-{d + 1:02d}T12:00:00Z", amount + d % 3, "Shop", "food")
        for d in range(n)
    ]


def test_columns_and_no_missing_values() -> None:
    X = build_features(frame(history(10)))
    assert list(X.columns) == FEATURE_NAMES
    assert not X.isna().any().any()


def test_changing_a_later_row_never_changes_earlier_features() -> None:
    rows = history(10) + [("A", "2025-03-20T12:00:00Z", 25.0, "Shop", "food")]
    before = build_features(frame(rows))
    rows[-1] = ("A", "2025-03-20T12:00:00Z", 99999.0, "Elsewhere", "travel")
    after = build_features(frame(rows))
    pd.testing.assert_frame_equal(before.iloc[:-1], after.iloc[:-1])


def test_amount_z_uses_only_earlier_rows_and_needs_history() -> None:
    rows = history(MIN_HISTORY + 3) + [("A", "2025-03-30T12:00:00Z", 500.0, "Shop", "food")]
    z = build_features(frame(rows))["amount_z"].to_numpy()
    assert (z[:MIN_HISTORY] == 0).all()  # not enough history yet: neutral
    assert z[-1] > 10  # 500 vs. an average of about 21


def test_new_merchant_and_category_have_zero_familiarity() -> None:
    rows = history(8) + [("A", "2025-03-30T12:00:00Z", 20.0, "NewPlace", "travel")]
    last = build_features(frame(rows)).iloc[-1]
    assert last["merchant_familiarity"] == 0 and last["category_familiarity"] == 0


def test_previous_hour_count_uses_real_seconds() -> None:
    """Would have caught the pandas 3 microsecond change (a 1-hour window became 41 days)."""
    times = ["10:00", "10:30", "10:59", "12:00", "12:30"]
    rows = [("A", f"2025-03-01T{t}:00Z", 10.0, "S", "c") for t in times]
    rows += [("A", "2025-03-05T12:00:00Z", 10.0, "S", "c")]  # days later: nothing in the hour
    assert build_features(frame(rows))["tx_last_hour"].tolist() == [0, 1, 2, 0, 1, 0]


def test_accounts_are_independent_and_input_order_is_preserved() -> None:
    rows = history(6, account="A") + history(6, amount=900.0, account="B")
    df = frame(rows).sample(frac=1.0, random_state=1)  # shuffled, custom index
    X = build_features(df)
    assert X.index.equals(df.index)
    expected = build_features(frame(rows))
    pd.testing.assert_frame_equal(X.sort_index(), expected.sort_index())


def test_explain_gives_readable_reasons() -> None:
    rows = history(10) + [("A", "2025-03-30T03:10:00Z", 900.0, "NewPlace", "food")]
    df = frame(rows)
    X = build_features(df)
    reasons = explain(X.iloc[-1], df["occurred_at"].iloc[-1])
    assert len(reasons) <= 3
    assert any("standard deviations" in r for r in reasons)
    assert any("First transaction at this merchant" in r for r in reasons)


@pytest.mark.parametrize("n", [1, 2])
def test_tiny_inputs_work(n: int) -> None:
    X = build_features(frame(history(n)))
    assert len(X) == n and np.isfinite(X.to_numpy()).all()

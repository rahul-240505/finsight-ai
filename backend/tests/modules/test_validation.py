"""CSV parsing and row rules. Pure functions, no database."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.transactions.validation import InvalidCsv, parse_csv
from tests.conftest import CSV_HEADER, make_csv

NOW = datetime(2025, 6, 1, tzinfo=UTC)


def parse(text: str, max_rows: int = 1000):
    return parse_csv(text.encode(), max_rows, now=NOW)


def one_row(**overrides: str):
    row = {
        "transaction_id": "T1",
        "account_id": "ACC-1",
        "timestamp": "2025-01-02T03:04:05Z",
        "amount": "12.50",
        "currency": "USD",
        "merchant": "Shop",
        "category": "groceries",
    } | overrides
    return parse(CSV_HEADER + ",".join(row.values()) + "\n")


def test_valid_file_parses_to_typed_rows() -> None:
    result = parse(make_csv(3))
    assert (result.total_rows, len(result.rows), result.error_count) == (3, 3, 0)
    first = result.rows[0]
    assert first.amount == Decimal("10.00") and first.occurred_at.tzinfo is not None


def test_offsets_are_converted_to_utc_and_bom_is_ignored() -> None:
    result = parse_csv(
        ("﻿" + CSV_HEADER + "T1,A,2025-01-02T05:00:00+05:30,1.00,USD,S,c\n").encode(),
        10,
        now=NOW,
    )
    assert result.rows[0].occurred_at == datetime(2025, 1, 1, 23, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("timestamp", "2025-01-02T03:04:05", "must include a timezone"),
        ("timestamp", "yesterday", "not an ISO 8601"),
        ("timestamp", "1999-12-31T00:00:00Z", "outside the allowed range"),
        ("timestamp", "2025-06-03T00:00:00Z", "outside the allowed range"),
        ("amount", "12.345", "more than 2 decimal places"),
        ("amount", "abc", "not a number"),
        ("amount", "NaN", "not a finite number"),
        ("amount", "1E+40", "too large"),
        ("currency", "usd", "not a supported"),
        ("currency", "XYZ", "not a supported"),
        ("merchant", "", "is required"),
        ("category", "x" * 51, "longer than 50"),
    ],
)
def test_bad_values_are_reported_with_line_and_column(field: str, value: str, message: str) -> None:
    result = one_row(**{field: value})
    assert result.error_count == 1 and not result.rows
    error = result.errors[0]
    assert (error.line, error.column) == (2, field) and message in error.message


def test_trailing_zeros_and_negative_amounts_are_fine() -> None:
    assert one_row(amount="12.500").rows[0].amount == Decimal("12.50")
    assert one_row(amount="-3.10").rows[0].amount == Decimal("-3.10")


def test_duplicate_ids_and_wrong_field_counts_are_row_errors() -> None:
    text = make_csv(2) + "T0,ACC,2025-01-03T00:00:00Z,1.00,USD,S,c\n" + "T9,only,three\n"
    result = parse(text)
    assert result.error_count == 2
    assert "more than once" in result.errors[0].message
    assert "wrong number of fields" in result.errors[1].message


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"\xff\xfe not utf-8", "not valid UTF-8"),
        (b"transaction_id,amount\nT1,1.00\n", "Missing required columns"),
        (CSV_HEADER.encode(), "no rows"),
        (b"", "Missing required columns"),
    ],
)
def test_file_level_problems_raise(data: bytes, message: str) -> None:
    with pytest.raises(InvalidCsv, match=message):
        parse_csv(data, 10, now=NOW)


def test_row_limit_is_enforced() -> None:
    with pytest.raises(InvalidCsv, match="more than 2 rows"):
        parse(make_csv(3), max_rows=2)


def test_only_first_50_errors_are_kept_but_all_are_counted() -> None:
    bad = "".join(f"T{i},A,not-a-date,1.00,USD,S,c\n" for i in range(80))
    result = parse(CSV_HEADER + bad)
    assert result.error_count == 80 and len(result.errors) == 50

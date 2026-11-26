"""CSV parsing and row validation for transaction imports.

Runs entirely in memory, before any database transaction is opened. Plain functions instead
of a Pydantic model per row: the same rules, about an order of magnitude less overhead per row,
which matters at hundreds of thousands of rows.

Expected header (extra columns are ignored):
    transaction_id,account_id,timestamp,amount,currency,merchant,category
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.core.errors import AppError

REQUIRED_COLUMNS = (
    "transaction_id",
    "account_id",
    "timestamp",
    "amount",
    "currency",
    "merchant",
    "category",
)
MAX_LENGTHS = {"transaction_id": 64, "account_id": 64, "merchant": 200, "category": 50}
# ISO 4217 codes accepted. A short allow-list catches typos that a 3-letter regex would accept.
CURRENCIES = frozenset(
    "AED AUD BRL CAD CHF CNY CZK DKK EUR GBP HKD HUF IDR ILS INR JPY KRW MXN MYR NOK NZD "
    "PHP PLN SAR SEK SGD THB TRY USD ZAR".split()
)
MAX_ABS_AMOUNT = Decimal("1000000000000")  # NUMERIC(14,2) holds up to 999,999,999,999.99
CENT = Decimal("0.01")
EARLIEST = datetime(2000, 1, 1, tzinfo=UTC)
MAX_REPORTED_ERRORS = 50


class InvalidCsv(AppError):
    """The file as a whole can't be used (encoding, header, size), or rows failed checks."""

    status_code, code, message = 422, "invalid_csv", "The CSV file is not valid."


@dataclass(frozen=True, slots=True)
class ValidRow:
    external_ref: str
    account_id: str
    occurred_at: datetime
    amount: Decimal
    currency: str
    merchant: str
    category: str


@dataclass(frozen=True, slots=True)
class RowError:
    line: int  # line number in the file; the header is line 1
    column: str | None
    message: str


@dataclass
class ParseResult:
    rows: list[ValidRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)  # first MAX_REPORTED_ERRORS only
    error_count: int = 0
    total_rows: int = 0


class _RowInvalid(Exception):
    def __init__(self, column: str, message: str) -> None:
        self.column, self.message = column, message


def _text(row: dict[str, str], column: str) -> str:
    value = (row.get(column) or "").strip()
    if not value:
        raise _RowInvalid(column, "is required")
    if len(value) > MAX_LENGTHS[column]:
        raise _RowInvalid(column, f"is longer than {MAX_LENGTHS[column]} characters")
    if any(ord(ch) < 32 for ch in value):
        raise _RowInvalid(column, "contains control characters")
    return value


def _timestamp(raw: str, latest: datetime) -> datetime:
    try:
        value = datetime.fromisoformat(raw.strip())
    except ValueError:
        raise _RowInvalid("timestamp", "is not an ISO 8601 date-time") from None
    if value.tzinfo is None:
        raise _RowInvalid("timestamp", "must include a timezone, e.g. 2025-05-01T13:45:00Z")
    value = value.astimezone(UTC)
    if not EARLIEST <= value <= latest:
        raise _RowInvalid("timestamp", "is outside the allowed range (2000-01-01 to tomorrow)")
    return value


def _amount(raw: str) -> Decimal:
    try:
        value = Decimal(raw.strip())
    except InvalidOperation:
        raise _RowInvalid("amount", "is not a number") from None
    if not value.is_finite():
        raise _RowInvalid("amount", "is not a finite number")
    # Size check first: quantize() itself raises on huge values like 1E+40.
    if abs(value) >= MAX_ABS_AMOUNT:
        raise _RowInvalid("amount", "is too large")
    if value.as_tuple().exponent < -2 and value != value.quantize(CENT):
        raise _RowInvalid("amount", "has more than 2 decimal places")
    return value.quantize(CENT)


def _currency(raw: str) -> str:
    value = raw.strip()
    if value not in CURRENCIES:
        raise _RowInvalid("currency", "is not a supported ISO 4217 code (e.g. USD, EUR, GBP)")
    return value


def parse_csv(data: bytes, max_rows: int, now: datetime | None = None) -> ParseResult:
    """Validate every row. File-level problems raise InvalidCsv; row problems are collected."""
    try:
        text = data.decode("utf-8-sig")  # -sig: tolerate the BOM Excel adds
    except UnicodeDecodeError:
        raise InvalidCsv("The file is not valid UTF-8 text.") from None

    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise InvalidCsv(f"Missing required columns: {', '.join(missing)}.")
    reader.fieldnames = header

    latest = (now or datetime.now(UTC)) + timedelta(days=1)
    result = ParseResult()
    seen_refs: set[str] = set()
    try:
        for row in reader:
            result.total_rows += 1
            if result.total_rows > max_rows:
                raise InvalidCsv(f"The file has more than {max_rows} rows.")
            try:
                if None in row or any(row[c] is None for c in REQUIRED_COLUMNS):
                    raise _RowInvalid("", "has the wrong number of fields")
                ref = _text(row, "transaction_id")
                if ref in seen_refs:
                    raise _RowInvalid("transaction_id", "appears more than once in the file")
                seen_refs.add(ref)
                result.rows.append(
                    ValidRow(
                        external_ref=ref,
                        account_id=_text(row, "account_id"),
                        occurred_at=_timestamp(row["timestamp"], latest),
                        amount=_amount(row["amount"]),
                        currency=_currency(row["currency"]),
                        merchant=_text(row, "merchant"),
                        category=_text(row, "category"),
                    )
                )
            except _RowInvalid as err:
                result.error_count += 1
                if len(result.errors) < MAX_REPORTED_ERRORS:
                    column = err.column or None
                    result.errors.append(RowError(reader.line_num, column, err.message))
    except csv.Error as exc:
        raise InvalidCsv(
            f"Line {reader.line_num}: the file is not well-formed CSV ({exc})."
        ) from None

    if result.total_rows == 0:
        raise InvalidCsv("The file has a header but no rows.")
    return result

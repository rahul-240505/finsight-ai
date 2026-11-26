"""Transaction queries. Every query starts with `owner_id = current user`.

Listing uses keyset pagination: the client sends back an opaque cursor holding the
(occurred_at, id) of the last row it saw, and the next page is "rows strictly older than
that". Unlike OFFSET, the database never reads and throws away the skipped rows, so page 1000
costs the same as page 1 (given the index on (owner_id, occurred_at, id)).
"""

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Select, select, tuple_
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, NotFound
from app.db.models import Transaction, User

MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class TransactionFilters:
    dataset_id: uuid.UUID | None = None
    account_id: str | None = None
    category: str | None = None
    date_from: date | None = None  # inclusive, UTC
    date_to: date | None = None  # exclusive, UTC
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None


def encode_cursor(row: Transaction) -> str:
    raw = json.dumps({"t": row.occurred_at.isoformat(), "id": str(row.id)})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["id"])
    except (ValueError, KeyError, TypeError):
        raise BadRequest("The cursor is not valid. Start again without it.") from None


def apply_filters(stmt: Select, user: User, f: TransactionFilters) -> Select:
    """Shared by listing and analytics, so both always mean the same rows."""
    stmt = stmt.where(Transaction.owner_id == user.id)
    if f.dataset_id is not None:
        stmt = stmt.where(Transaction.dataset_id == f.dataset_id)
    if f.account_id is not None:
        stmt = stmt.where(Transaction.account_id == f.account_id)
    if f.category is not None:
        stmt = stmt.where(Transaction.category == f.category)
    if f.date_from is not None:
        stmt = stmt.where(Transaction.occurred_at >= f.date_from)
    if f.date_to is not None:
        stmt = stmt.where(Transaction.occurred_at < f.date_to)
    if f.min_amount is not None:
        stmt = stmt.where(Transaction.amount >= f.min_amount)
    if f.max_amount is not None:
        stmt = stmt.where(Transaction.amount <= f.max_amount)
    return stmt


def list_page(
    db: Session, user: User, filters: TransactionFilters, limit: int, cursor: str | None
) -> tuple[list[Transaction], str | None]:
    """Newest first. Returns the rows and the cursor for the next page (None at the end)."""
    stmt = apply_filters(select(Transaction), user, filters)
    if cursor:
        last_time, last_id = decode_cursor(cursor)
        stmt = stmt.where(tuple_(Transaction.occurred_at, Transaction.id) < (last_time, last_id))
    limit = min(limit, MAX_PAGE_SIZE)
    # Fetch one extra row to know whether another page exists, without a COUNT(*).
    stmt = stmt.order_by(Transaction.occurred_at.desc(), Transaction.id.desc()).limit(limit + 1)
    rows = list(db.scalars(stmt))
    next_cursor = encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return rows[:limit], next_cursor


def get_owned(db: Session, user: User, transaction_id: uuid.UUID) -> Transaction:
    stmt = select(Transaction).where(
        Transaction.id == transaction_id, Transaction.owner_id == user.id
    )
    row = db.scalar(stmt)
    if row is None:
        raise NotFound()
    return row

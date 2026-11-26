"""Transaction listing and analytics. All reads, all owner-scoped."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.api.deps import DbSession, require_permission
from app.core.permissions import Permission
from app.db.models import User
from app.modules.transactions import analytics, service
from app.modules.transactions.service import TransactionFilters

router = APIRouter(tags=["transactions"])

Reader = Annotated[User, Depends(require_permission(Permission.DATASET_READ))]


class TransactionOut(BaseModel):
    """Amounts are JSON strings ("12.50"), so no float rounding happens on the way out."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    external_ref: str
    account_id: str
    occurred_at: datetime
    amount: Decimal
    currency: str
    merchant: str
    category: str


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    next_cursor: str | None


def filters(
    dataset_id: uuid.UUID | None = None,
    account_id: Annotated[str | None, Query(max_length=64)] = None,
    category: Annotated[str | None, Query(max_length=50)] = None,
    date_from: Annotated[date | None, Query(description="Inclusive, UTC")] = None,
    date_to: Annotated[date | None, Query(description="Exclusive, UTC")] = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
) -> TransactionFilters:
    return TransactionFilters(
        dataset_id, account_id, category, date_from, date_to, min_amount, max_amount
    )


Filters = Annotated[TransactionFilters, Depends(filters)]


@router.get("/transactions")
def list_transactions(
    db: DbSession,
    user: Reader,
    f: Filters,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE_SIZE)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> TransactionPage:
    """Newest first. Keyset pagination: pass `next_cursor` from the previous page as `cursor`."""
    rows, next_cursor = service.list_page(db, user, f, limit, cursor)
    return TransactionPage(
        items=[TransactionOut.model_validate(r) for r in rows], next_cursor=next_cursor
    )


@router.get("/transactions/{transaction_id}")
def get_transaction(transaction_id: uuid.UUID, db: DbSession, user: Reader) -> TransactionOut:
    return TransactionOut.model_validate(service.get_owned(db, user, transaction_id))


@router.get("/analytics/summary")
def summary(db: DbSession, user: Reader, f: Filters) -> dict:
    """Totals, averages, min/max per currency, plus breakdowns by category and by month.
    Takes the same filters as the transaction list."""
    return analytics.summary(db, user, f)

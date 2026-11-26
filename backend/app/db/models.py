"""ORM models. Postgres is the system of record (ADR-002)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.permissions import Role
from app.db.base import Base, TimestampMixin

ROLE_VALUES = ", ".join(f"'{r.value}'" for r in Role)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(f"role IN ({ROLE_VALUES})", name="role_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Stored lower-cased by the service, so UNIQUE is effectively case-insensitive.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=Role.ANALYST.value)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(TimestampMixin, Base):
    """Server-side login session. Only a SHA-256 of the cookie token is stored, so a database
    leak does not hand out live sessions."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")


class Dataset(TimestampMixin, Base):
    """One imported transaction file. Created only when every row is valid (all-or-nothing)."""

    __tablename__ = "datasets"
    __table_args__ = (
        # Target of the composite FK from transactions: guarantees a row's owner_id always
        # equals its dataset's owner_id.
        UniqueConstraint("id", "owner_id", name="uq_datasets_id_owner"),
        # The same file can't be imported twice by the same user. NULL for datasets created
        # before imports existed (Postgres allows many NULLs in a UNIQUE constraint).
        UniqueConstraint("owner_id", "content_hash", name="uq_datasets_owner_content"),
        CheckConstraint("status IN ('imported')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), server_default="imported")
    row_count: Mapped[int] = mapped_column(Integer, server_default="0")
    content_hash: Mapped[str | None] = mapped_column(String(64))


class Transaction(Base):
    """One money movement. owner_id is copied from the dataset so every query can filter by
    owner directly (and use owner-first indexes) without a join."""

    __tablename__ = "transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "owner_id"],
            ["datasets.id", "datasets.owner_id"],
            ondelete="CASCADE",
            name="fk_transactions_dataset_owner",
        ),
        UniqueConstraint("dataset_id", "external_ref", name="uq_transactions_dataset_ref"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        # Owner first (every query filters on it), then the filter column, then the sort
        # columns, so a page is read straight off the index in API order with no sort step.
        # Measured before/after in docs/evaluation.md.
        Index("ix_transactions_owner_time", "owner_id", "occurred_at", "id"),
        Index("ix_transactions_owner_account_time", "owner_id", "account_id", "occurred_at", "id"),
        Index("ix_transactions_owner_category_time", "owner_id", "category", "occurred_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column()
    owner_id: Mapped[uuid.UUID] = mapped_column()
    external_ref: Mapped[str] = mapped_column(String(64))  # transaction_id from the file
    account_id: Mapped[str] = mapped_column(String(64))  # the customer account in the data
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    merchant: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50))


class IdempotencyRecord(TimestampMixin, Base):
    """Remembers the outcome of a request sent with an Idempotency-Key, so a retry returns
    the saved response instead of doing the work again."""

    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

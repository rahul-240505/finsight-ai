"""ORM models. Postgres is the system of record (ADR-002)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
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


class ModelVersion(TimestampMixin, Base):
    """A trained model file plus everything needed to trust and reproduce it."""

    __tablename__ = "model_versions"
    __table_args__ = (
        # At most one active version per model name; the database enforces it.
        Index(
            "uq_model_versions_active_name", "name", unique=True, postgresql_where=text("is_active")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))  # e.g. "isolation_forest"
    version: Mapped[str] = mapped_column(String(100), unique=True)
    algorithm: Mapped[str] = mapped_column(String(100))
    feature_names: Mapped[list[str]] = mapped_column(JSONB)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    threshold: Mapped[float] = mapped_column(Float)  # risk_score >= threshold → flagged
    training_data: Mapped[str] = mapped_column(String(500))  # dataset, seed, split description
    artifact_path: Mapped[str] = mapped_column(String(500))  # relative to settings.model_dir
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class RiskAssessment(TimestampMixin, Base):
    """One model's opinion of one transaction: a score, a flag and readable reasons.
    "Flagged" means unusual and worth a human look, never "fraud"."""

    __tablename__ = "risk_assessments"
    __table_args__ = (
        UniqueConstraint("transaction_id", "model_version_id", name="uq_risk_tx_model"),
        # Review queue: one dataset's assessments, highest score first.
        Index(
            "ix_risk_owner_dataset_model_score",
            "owner_id",
            "dataset_id",
            "model_version_id",
            "risk_score",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE")
    )
    owner_id: Mapped[uuid.UUID] = mapped_column()
    dataset_id: Mapped[uuid.UUID] = mapped_column()
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE")
    )
    risk_score: Mapped[float] = mapped_column(Float)
    is_flagged: Mapped[bool] = mapped_column(Boolean)
    reasons: Mapped[list[str]] = mapped_column(JSONB)


class Document(TimestampMixin, Base):
    """An uploaded PDF. Its text lives in document_chunks; Qdrant holds only the vectors."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_documents_id_owner"),
        # The same file is indexed once per user; re-uploading returns the existing document.
        UniqueConstraint("owner_id", "content_hash", name="uq_documents_owner_content"),
        CheckConstraint("status IN ('indexing', 'ready')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer)
    # "indexing" until the vectors are stored; only "ready" documents are searched.
    status: Mapped[str] = mapped_column(String(20), server_default="indexing")
    # What produced the vectors, so a model or chunker change can find what to re-index.
    embedding_model: Mapped[str] = mapped_column(String(100))
    chunker_version: Mapped[str] = mapped_column(String(20))


class DocumentChunk(Base):
    """A passage from one page. Its id is also its Qdrant point id."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "owner_id"],
            ["documents.id", "documents.owner_id"],
            ondelete="CASCADE",
            name="fk_document_chunks_document_owner",
        ),
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_doc_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column()
    owner_id: Mapped[uuid.UUID] = mapped_column()
    chunk_index: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)  # 1-based, as people cite pages
    text: Mapped[str] = mapped_column(Text)

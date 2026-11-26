"""ORM models. Postgres is the system of record (ADR-002)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
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
    """A user's uploaded transaction dataset. Phase 2 adds import status, row counts and rows."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))

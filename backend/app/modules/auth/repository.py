"""Database access for users and sessions. No business rules here."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import User, UserSession


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def get_user(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def add_user(db: Session, email: str, password_hash: str, role: str) -> User:
    user = User(email=email, password_hash=password_hash, role=role)
    db.add(user)
    db.flush()  # assigns defaults and surfaces UNIQUE violations now, inside the caller's txn
    return user


def add_session(db: Session, user_id: uuid.UUID, token_hash: str, expires_at: datetime) -> None:
    db.add(UserSession(user_id=user_id, token_hash=token_hash, expires_at=expires_at))


def get_live_session(db: Session, token_hash: str) -> UserSession | None:
    """A session that exists and hasn't expired. The user is loaded in the same query."""
    now = datetime.now(UTC)
    stmt = select(UserSession).where(
        UserSession.token_hash == token_hash, UserSession.expires_at > now
    )
    return db.scalar(stmt)


def delete_session(db: Session, token_hash: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == token_hash))


def delete_user_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(delete(UserSession).where(UserSession.user_id == user_id))

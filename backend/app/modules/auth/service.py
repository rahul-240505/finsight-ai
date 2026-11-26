"""Auth business rules: register, login, logout, resolve the current user, change roles."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, Unauthorized
from app.core.permissions import Role
from app.db.models import User
from app.modules.auth import repository as repo

INVALID_LOGIN = "Email or password is incorrect."


def normalise_email(email: str) -> str:
    return email.strip().lower()


def register(db: Session, email: str, password: str, role: Role = Role.ANALYST) -> User:
    """Self-registration always creates an analyst; only an admin can grant other roles."""
    email = normalise_email(email)
    password_hash = security.hash_password(password)  # slow: done before touching the DB
    try:
        user = repo.add_user(db, email, password_hash, role.value)
        db.commit()
    except IntegrityError as exc:
        # The UNIQUE constraint is the real guard: two simultaneous registrations can both
        # pass a "does it exist?" check, but only one insert can win.
        db.rollback()
        raise Conflict("An account with this email already exists.") from exc
    return user


def login(db: Session, email: str, password: str) -> tuple[User, str]:
    """Return the user and a new raw session token. Every failure gives the same message."""
    user = repo.get_user_by_email(db, normalise_email(email))
    # Always run one Argon2 verify, even for unknown emails (constant-ish timing).
    ok = security.verify_password(user.password_hash if user else None, password)
    if user is None or not ok or user.disabled_at is not None:
        raise Unauthorized(INVALID_LOGIN)

    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)

    token = security.new_session_token()
    expires_at = datetime.now(UTC) + timedelta(hours=get_settings().session_ttl_hours)
    repo.add_session(db, user.id, security.hash_session_token(token), expires_at)
    db.commit()
    return user, token


def logout(db: Session, token: str) -> None:
    repo.delete_session(db, security.hash_session_token(token))
    db.commit()


def user_for_token(db: Session, token: str) -> User | None:
    """The signed-in user for a cookie token, or None if missing, expired or disabled."""
    session = repo.get_live_session(db, security.hash_session_token(token))
    if session is None or session.user.disabled_at is not None:
        return None
    return session.user


def set_role(db: Session, user_id: uuid.UUID, role: Role) -> User:
    """Admin-only (enforced by the route). Existing sessions are ended so the change applies
    immediately and a demoted user can't keep using old rights."""
    user = repo.get_user(db, user_id)
    if user is None:
        raise NotFound()
    user.role = role.value
    repo.delete_user_sessions(db, user.id)
    db.commit()
    return user

"""Shared FastAPI dependencies: database session, current user, permission checks."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Forbidden, Unauthorized
from app.core.permissions import Permission, has_permission
from app.db.models import User
from app.db.session import get_db
from app.modules.auth import service as auth_service

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DbSession) -> User:
    """401 unless the request carries a live session cookie for an active user."""
    token = request.cookies.get(get_settings().session_cookie_name)
    user = auth_service.user_for_token(db, token) if token else None
    if user is None:
        raise Unauthorized()
    request.state.user_id = user.id  # for the access log
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: Permission) -> Callable[[User], User]:
    """Route guard: signed in (401) and the role grants `permission` (403)."""

    def checker(user: CurrentUser) -> User:
        if not has_permission(user.role, permission):
            raise Forbidden()
        return user

    return checker

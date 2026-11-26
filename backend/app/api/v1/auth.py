"""Auth routes: register, login, logout, me. Thin: parse input, call the service, shape output."""

from typing import Annotated

import redis
from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import CurrentUser, DbSession
from app.core import rate_limit
from app.core.config import get_settings
from app.core.rate_limit import get_redis
from app.modules.auth import service
from app.modules.auth.schemas import Credentials, LoginRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: Credentials, db: DbSession) -> UserOut:
    user = service.register(db, body.email, body.password)
    return UserOut.model_validate(user)


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    limiter: Annotated[redis.Redis, Depends(get_redis)],
) -> UserOut:
    """Sets the session cookie. HttpOnly: JavaScript can't read it. Secure: HTTPS only
    (browsers treat http://localhost as secure). SameSite=Lax: not sent on cross-site POSTs.

    Rate limited per client IP and per email address (every attempt counts, successful or
    not), which slows password guessing against one account and from one machine."""
    rate_limit.hit(limiter, "login_ip", rate_limit.client_ip(request))
    email_key = rate_limit.subject_hash(service.normalise_email(body.email))
    rate_limit.hit(limiter, "login_email", email_key)
    user, token = service.login(db, body.email, body.password)
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DbSession, _: CurrentUser) -> None:
    """Deletes the server-side session, so the token is dead even if it was copied."""
    name = get_settings().session_cookie_name
    service.logout(db, request.cookies[name])
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)

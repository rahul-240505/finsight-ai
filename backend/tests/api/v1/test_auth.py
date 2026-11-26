"""Register, login, logout and session handling against a real Postgres."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import User, UserSession
from tests.conftest import PASSWORD, login

pytestmark = pytest.mark.integration


def test_register_creates_analyst_and_never_returns_hash(api: TestClient) -> None:
    response = api.post(
        "/api/v1/auth/register", json={"email": "New@Example.com", "password": PASSWORD}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com" and body["role"] == "analyst"
    assert "password" not in response.text and "argon2" not in response.text


def test_duplicate_email_is_409_case_insensitive(api: TestClient) -> None:
    payload = {"email": "dup@example.com", "password": PASSWORD}
    assert api.post("/api/v1/auth/register", json=payload).status_code == 201
    payload["email"] = "DUP@example.com"
    response = api.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409


def test_short_password_rejected(api: TestClient) -> None:
    response = api.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "x"})
    assert response.status_code == 422


def test_login_sets_hardened_cookie_and_me_works(api: TestClient, make_user: Callable) -> None:
    user = make_user()
    response = api.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert api.get("/api/v1/auth/me").json()["email"] == user.email


def test_wrong_password_and_unknown_email_look_identical(
    api: TestClient, make_user: Callable
) -> None:
    user = make_user()
    wrong = api.post("/api/v1/auth/login", json={"email": user.email, "password": "nope"})
    unknown = api.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_disabled_user_cannot_log_in_or_use_old_session(
    api: TestClient, db: Session, make_user: Callable
) -> None:
    user = make_user()
    login(api, user)
    db.execute(update(User).where(User.id == user.id).values(disabled_at=datetime.now(UTC)))
    assert api.get("/api/v1/auth/me").status_code == 401
    response = api.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 401


def test_logout_kills_the_token_even_if_it_was_copied(api: TestClient, make_user: Callable) -> None:
    login(api, make_user())
    stolen = api.cookies.get("finsight_session")
    assert api.post("/api/v1/auth/logout").status_code == 204
    assert api.cookies.get("finsight_session") is None  # browser was told to drop it
    api.cookies.set("finsight_session", stolen)  # attacker replays a copied token
    assert api.get("/api/v1/auth/me").status_code == 401


def test_expired_session_is_rejected(api: TestClient, db: Session, make_user: Callable) -> None:
    login(api, make_user())
    past = datetime.now(UTC) - timedelta(seconds=1)
    db.execute(update(UserSession).values(expires_at=past))
    assert api.get("/api/v1/auth/me").status_code == 401


def test_database_stores_only_a_hash_of_the_token(
    api: TestClient, db: Session, make_user: Callable
) -> None:
    login(api, make_user())
    token = api.cookies.get("finsight_session")
    stored = db.scalars(select(UserSession.token_hash)).all()
    assert token not in stored and len(stored) == 1

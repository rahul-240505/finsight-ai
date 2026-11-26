"""Rate limits: 429 with Retry-After past the limit, per user, and fail-open without Redis."""

import time
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.core.config import get_settings
from app.core.rate_limit import get_redis
from tests.conftest import PASSWORD, login

pytestmark = pytest.mark.integration


def ask(api: TestClient):
    return api.post("/api/v1/answers", json={"question": "What is the reporting window?"})


def test_answers_limit_is_per_user(
    api: TestClient, make_user: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(get_settings().rate_limits, "answers", "2/60")
    login(api, make_user())
    assert [ask(api).status_code for _ in range(3)] == [200, 200, 429]
    limited = ask(api)
    assert limited.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    login(api, make_user())
    assert ask(api).status_code == 200  # another user has their own counter


def test_login_limit_per_email_counts_every_attempt(
    api: TestClient, make_user: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(get_settings().rate_limits, "login_email", "3/300")
    user = make_user()
    wrong = {"email": user.email, "password": "wrong-password-123"}
    assert [api.post("/api/v1/auth/login", json=wrong).status_code for _ in range(3)] == [401] * 3
    right = {"email": user.email.upper(), "password": PASSWORD}  # same account, other casing
    assert api.post("/api/v1/auth/login", json=right).status_code == 429


def test_limiter_fails_open_fast_when_redis_is_down(
    api: TestClient, make_user: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requests pass, and quickly: no client retries, and a cool-down after the first error."""
    monkeypatch.setitem(get_settings().rate_limits, "answers", "1/60")
    monkeypatch.setattr(rate_limit, "_skip_until", 0.0)
    api.app.dependency_overrides[get_redis] = lambda: rate_limit.make_client("redis://127.0.0.1:1")
    login(api, make_user())
    started = time.perf_counter()
    assert [ask(api).status_code for _ in range(3)] == [200, 200, 200]
    assert time.perf_counter() - started < 1.0
    assert rate_limit._skip_until > 0  # cool-down engaged

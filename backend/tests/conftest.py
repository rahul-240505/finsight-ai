"""Shared fixtures.

Unit tests use `client` (no database). Integration tests use `api` + `db`: a separate
`<name>_test` database, migrated once per run, with every test wrapped in a transaction that is
rolled back afterwards, so tests never see each other's data.
"""

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.permissions import Role
from app.db.models import User
from app.db.session import get_db
from app.main import create_app
from app.modules.auth import service as auth_service

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
PASSWORD = "correct-horse-battery"  # test-only, meets the 12-character policy
BASE_URL = "https://testserver"  # https, so the Secure session cookie is sent back


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient around a fresh app per test, so overrides never leak between tests."""
    with TestClient(create_app(), base_url=BASE_URL) as c:
        yield c


def fresh_database(suffix: str) -> str:
    """(Re)create an empty database next to the configured one and return its URL."""
    url = make_url(get_settings().database_url.get_secret_value())
    name = f"{url.database}_{suffix}"
    admin_dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')
    return url.set(database=name).render_as_string(hide_password=False)


def alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["url"] = url
    return cfg


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    url = fresh_database("test")
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(test_engine: Engine) -> Iterator[Session]:
    """Session inside an outer transaction. Service commits become savepoints, and the outer
    transaction is rolled back at the end, so nothing persists between tests."""
    with test_engine.connect() as conn:
        outer = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


@pytest.fixture
def api(db: Session) -> Iterator[TestClient]:
    """TestClient whose requests all use the test's `db` session."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app, base_url=BASE_URL) as c:
        yield c


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    counter = iter(range(1_000_000))

    def _make(role: Role = Role.ANALYST, email: str | None = None) -> User:
        email = email or f"user{next(counter)}@example.com"
        return auth_service.register(db, email, PASSWORD, role)

    return _make


def login(client: TestClient, user: User) -> TestClient:
    """Sign `client` in as `user` (the cookie jar keeps the session cookie)."""
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


CSV_HEADER = "transaction_id,account_id,timestamp,amount,currency,merchant,category\n"


def make_csv(rows: int = 3, start: int = 0, currency: str = "USD") -> str:
    """A small valid CSV: one row per day of January 2025, amounts 10.00, 11.00, ..."""
    lines = [
        f"T{i},ACC-{i % 2},2025-01-{i % 28 + 1:02d}T12:00:00Z,{10 + i}.00,{currency},"
        f"Shop {i % 3},{'groceries' if i % 2 else 'travel'}\n"
        for i in range(start, start + rows)
    ]
    return CSV_HEADER + "".join(lines)


def upload(client: TestClient, csv_text: str, name: str = "test", key: str | None = None):
    """POST a CSV import. A unique Idempotency-Key is generated unless one is given."""
    headers = {"Content-Type": "text/csv", "Idempotency-Key": key or str(uuid.uuid4())}
    return client.post(
        "/api/v1/datasets", params={"name": name}, content=csv_text.encode(), headers=headers
    )

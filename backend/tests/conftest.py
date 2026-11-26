"""Shared fixtures.

Unit tests use `client` (no database). Integration tests use `api` + `db`: a separate
`<name>_test` database, migrated once per run, with every test wrapped in a transaction that is
rolled back afterwards, so tests never see each other's data.
"""

import contextlib
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
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
from app.modules.jobs.runner import Deps, RetryLater, run_job
from app.services.llm import FakeProvider, get_llm
from app.services.vector_store import QdrantStore, VectorStoreUnavailable, get_vector_store
from app.worker.queue import InlineQueue, get_job_queue

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
PASSWORD = "correct-horse-battery"  # test-only, meets the 12-character policy
BASE_URL = "https://testserver"  # https, so the Secure session cookie is sent back


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tests marked `ollama` need a local model server: skip them in CI and when it's down."""
    settings = get_settings()
    reason = None
    if settings.app_env == "ci":
        reason = "no Ollama in CI"
    else:
        try:
            httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=1.0).raise_for_status()
        except httpx.HTTPError:
            reason = "Ollama is not running"
    if reason:
        for item in items:
            if "ollama" in item.keywords:
                item.add_marker(pytest.mark.skip(reason=reason))


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


@pytest.fixture(scope="session")
def vector_store() -> Iterator[QdrantStore]:
    """A throwaway Qdrant collection for this test run (Qdrant has no rollback, so tests stay
    apart by using fresh users; the collection is dropped at the end)."""
    store = QdrantStore(get_settings(), collection=f"test_chunks_{uuid.uuid4().hex[:8]}")
    yield store
    with contextlib.suppress(VectorStoreUnavailable):
        store.drop_collection()


@pytest.fixture
def fake_llm() -> FakeProvider:
    return FakeProvider(dim=get_settings().embed_dim)


@pytest.fixture
def inline_queue(db: Session, fake_llm: FakeProvider, vector_store: QdrantStore) -> InlineQueue:
    """Runs each job immediately inside the request, on the test's session and fakes, with
    the worker's retry behaviour (RetryLater → try again, up to job_max_attempts)."""
    deps = Deps(llm=fake_llm, store=vector_store)

    def run(job_id: uuid.UUID) -> None:
        for _ in range(get_settings().job_max_attempts):
            try:
                run_job(job_id, db, deps)
                return
            except RetryLater:
                continue

    return InlineQueue(run)


@pytest.fixture
def api(
    db: Session,
    fake_llm: FakeProvider,
    vector_store: QdrantStore,
    inline_queue: InlineQueue,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[TestClient]:
    """TestClient whose requests use the test's `db` session, the fake model (no test can
    reach Ollama by accident), the test Qdrant collection, an inline job queue, a private
    upload folder, and rate-limit counters no other test shares."""
    settings = get_settings()
    # Hashed bag-of-words similarities run lower than real embeddings: a question sharing a
    # few words with a passage scores about 0.2-0.4, an unrelated one about 0.
    monkeypatch.setattr(settings, "rag_min_score", 0.1)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "rate_limit_prefix", f"test-rl:{uuid.uuid4().hex}")
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_llm] = lambda: fake_llm
    app.dependency_overrides[get_vector_store] = lambda: vector_store
    app.dependency_overrides[get_job_queue] = lambda: inline_queue
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


def upload_pdf(client: TestClient, pdf: bytes, name: str = "policy.pdf"):
    return client.post(
        "/api/v1/documents",
        params={"name": name},
        content=pdf,
        headers={"Content-Type": "application/pdf"},
    )


def job_of(client: TestClient, response) -> dict:
    """Follow a 202's Location header to the job."""
    assert response.status_code == 202, response.text
    job = client.get(response.headers["location"])
    assert job.status_code == 200, job.text
    return job.json()


def import_csv(client: TestClient, csv_text: str, name: str = "test", key: str | None = None):
    """Import through the job API and return the new dataset's id."""
    job = job_of(client, upload(client, csv_text, name=name, key=key))
    assert job["status"] == "succeeded", job
    return job["result"]["dataset_id"]


def index_pdf(client: TestClient, pdf: bytes, name: str = "policy.pdf") -> str:
    """Upload and index a PDF through the job API; return the document id."""
    response = upload_pdf(client, pdf, name)
    if response.status_code == 200:  # already indexed
        return response.json()["id"]
    job = job_of(client, response)
    assert job["status"] == "succeeded", job
    return job["result"]["document_id"]

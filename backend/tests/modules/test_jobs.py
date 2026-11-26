"""Job runner: retries, failure kinds, duplicate delivery, stale claims, re-delivery, RQ."""

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from rq import Queue
from rq.job import Job as RQJob
from rq.timeouts import JobTimeoutException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFound
from app.db.models import Job
from app.modules.jobs import runner
from app.modules.jobs import service as jobs
from app.services.llm import ModelUnavailable
from app.worker.queue import TASK, RQJobQueue, get_job_queue
from tests.conftest import login, make_csv, upload

pytestmark = pytest.mark.integration


class Calls(list):
    """Records handler calls; `script` lists what each call returns or raises."""

    def __init__(self) -> None:
        super().__init__()
        self.script: list[object] = []


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    """Replace the real handlers with one whose behaviour each test scripts."""
    log = Calls()

    def handler(db, user, payload, deps) -> dict:
        log.append(payload["n"])
        step = log.script.pop(0) if log.script else {"ok": True}
        if isinstance(step, BaseException):
            raise step
        return step

    monkeypatch.setattr(runner, "_handlers", lambda: {"risk_scoring": handler})
    return log


def new_job(db: Session, owner_id: uuid.UUID, **values: object) -> Job:
    job = jobs.add(db, owner_id, "risk_scoring", uuid.uuid4().hex, {"n": "x"}).job
    for key, value in values.items():
        setattr(job, key, value)
    db.commit()
    return job


def run(db: Session, job: Job) -> str:
    return runner.run_job(job.id, db, runner.Deps(llm=None, store=None))  # type: ignore[arg-type]


def test_transient_error_is_retried_then_succeeds(db: Session, make_user: Callable, calls) -> None:
    job = new_job(db, make_user().id)
    calls.script.extend([ModelUnavailable(), {"scored": 3}])
    with pytest.raises(runner.RetryLater):
        run(db, job)
    db.refresh(job)
    assert (job.status, job.attempts, job.error["code"]) == ("queued", 1, "model_unavailable")
    assert run(db, job) == "succeeded"
    db.refresh(job)
    assert (job.attempts, job.result, job.error) == (2, {"scored": 3}, None)


def test_transient_error_fails_after_max_attempts(db: Session, make_user: Callable, calls) -> None:
    job = new_job(db, make_user().id)
    calls.script.extend([ModelUnavailable()] * 3)
    for _ in range(get_settings().job_max_attempts - 1):
        with pytest.raises(runner.RetryLater):
            run(db, job)
    assert run(db, job) == "failed"
    db.refresh(job)
    assert (job.attempts, job.error["code"]) == (3, "model_unavailable")
    assert job.finished_at is not None


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (NotFound(), "not_found"),
        (JobTimeoutException("too slow"), "job_timeout"),
        (KeyError("secret detail"), "internal_error"),
    ],
)
def test_permanent_errors_fail_at_once_with_a_safe_message(
    db: Session, make_user: Callable, calls, exc: Exception, code: str
) -> None:
    job = new_job(db, make_user().id)
    calls.script.append(exc)
    assert run(db, job) == "failed"
    db.refresh(job)
    assert (job.attempts, job.error["code"]) == (1, code)
    assert "secret detail" not in str(job.error)


def test_duplicate_delivery_does_nothing(db: Session, make_user: Callable, calls) -> None:
    job = new_job(db, make_user().id)
    assert run(db, job) == "succeeded"
    assert run(db, job) == "skipped"
    assert calls == ["x"]  # the handler ran once


def test_running_job_is_claimed_again_only_when_stale(db: Session, make_user: Callable) -> None:
    owner = make_user().id
    fresh = new_job(db, owner, status="running", started_at=datetime.now(UTC), attempts=1)
    assert jobs.claim(db, fresh.id) is None  # another worker is on it
    old = datetime.now(UTC) - timedelta(seconds=get_settings().job_stale_after_seconds + 60)
    stale = new_job(db, owner, status="running", started_at=old, attempts=1)
    claimed = jobs.claim(db, stale.id)
    assert claimed is not None and claimed.attempts == 2


def test_disabled_owner_fails_the_job(db: Session, make_user: Callable, calls) -> None:
    user = make_user()
    job = new_job(db, user.id)
    user.disabled_at = datetime.now(UTC)
    db.commit()
    assert run(db, job) == "failed" and calls == []


def test_lost_jobs_are_found_for_redelivery(db: Session, make_user: Callable) -> None:
    owner = make_user().id
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    lost_queued = new_job(db, owner, created_at=long_ago)
    lost_running = new_job(db, owner, status="running", started_at=long_ago, attempts=1)
    new_job(db, owner)  # just created: not lost
    new_job(db, owner, status="succeeded", created_at=long_ago)
    found = {j.id for j in jobs.needing_requeue(db, older_than_seconds=60)}
    assert found == {lost_queued.id, lost_running.id}


def test_rq_enqueue_sets_task_timeout_and_retries() -> None:
    settings = get_settings()
    queue = RQJobQueue(settings.redis_url, f"test-{uuid.uuid4().hex[:8]}")
    job_id = uuid.uuid4()
    try:
        queue.enqueue(job_id, "document_index")
        rq_job = RQJob.fetch(str(job_id), connection=queue.queue.connection)
        assert rq_job.func_name == TASK and rq_job.args == (str(job_id),)
        assert rq_job.timeout == 300
        assert rq_job.retries_left == settings.job_max_attempts - 1
    finally:
        queue.queue.empty()
        Queue(queue.queue.name, connection=queue.queue.connection).delete(delete_jobs=True)


def test_enqueue_with_redis_down_leaves_the_job_queued(
    api: TestClient, make_user: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The job row is committed before enqueueing, so nothing is lost; the sweep delivers it."""
    api.app.dependency_overrides[get_job_queue] = lambda: RQJobQueue("redis://127.0.0.1:1", "x")
    login(api, make_user())
    started = time.perf_counter()
    response = upload(api, make_csv(2))
    assert time.perf_counter() - started < 1.0  # no retry back-off
    assert response.status_code == 202 and response.json()["status"] == "queued"
    assert api.get(response.headers["location"]).json()["status"] == "queued"


def test_jobs_are_private(api: TestClient, make_user: Callable) -> None:
    login(api, make_user())
    location = upload(api, make_csv(2)).headers["location"]
    assert len(api.get("/api/v1/jobs").json()) == 1
    login(api, make_user())
    assert api.get(location).status_code == 404
    assert api.get("/api/v1/jobs").json() == []

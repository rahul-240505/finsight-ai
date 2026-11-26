"""Delivering job ids to the worker. RQ over Redis in normal use; an inline queue in tests."""

import logging
import uuid
from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry as RedisRetry
from rq import Queue, Retry

from app.core.config import get_settings
from app.core.errors import AppError

if TYPE_CHECKING:
    from app.db.models import Job

logger = logging.getLogger(__name__)

# Per-kind hard time limits. RQ kills a job that runs longer (the work horse process is
# terminated), which also bounds a malicious PDF that makes the parser spin.
TIMEOUTS = {
    "dataset_import": 900,
    "risk_scoring": 900,
    "document_index": 300,
    "investigation": 300,  # above agent_timeout_seconds, which stops the loop first
}
TASK = "app.worker.tasks.execute"


class QueueUnavailable(AppError):
    status_code, code = 503, "queue_unavailable"
    message = "The job queue is not reachable. Try again later."


class JobQueue(Protocol):
    def enqueue(self, job_id: uuid.UUID, kind: str) -> None: ...


class RQJobQueue:
    def __init__(self, redis_url: str, name: str) -> None:
        # No client retries: with Redis down, the request should fail over to "stays queued"
        # in milliseconds, not after redis-py's ~4 s of retry back-off.
        connection = redis.Redis.from_url(
            redis_url, socket_connect_timeout=2, socket_timeout=5, retry=RedisRetry(NoBackoff(), 0)
        )
        self.queue = Queue(name, connection=connection)

    def enqueue(self, job_id: uuid.UUID, kind: str) -> None:
        # Retries happen in our runner (it knows which errors are transient), so RQ's own
        # Retry is only a safety net for the work horse being killed, e.g. by the timeout.
        max_attempts = get_settings().job_max_attempts
        try:
            self.queue.enqueue_call(
                TASK,
                args=(str(job_id),),
                timeout=TIMEOUTS[kind],
                job_id=f"{job_id}",
                result_ttl=3600,
                failure_ttl=7 * 24 * 3600,
                retry=Retry(max=max_attempts - 1, interval=[5, 30]) if max_attempts > 1 else None,
            )
        except redis.RedisError as exc:
            logger.warning("enqueue failed for job %s: %s", job_id, type(exc).__name__)
            raise QueueUnavailable() from exc


class InlineQueue:
    """Runs the job straight away in the caller's process. For tests and local scripts."""

    def __init__(self, run: Callable[[uuid.UUID], None]) -> None:
        self.run = run
        self.enqueued: list[uuid.UUID] = []

    def enqueue(self, job_id: uuid.UUID, kind: str) -> None:
        self.enqueued.append(job_id)
        self.run(job_id)


def enqueue_or_leave_queued(queue: JobQueue, job: "Job") -> None:
    """The job row is committed first, so a failed enqueue loses nothing: it stays queued and
    the worker's start-up sweep (or `python -m app.cli requeue`) delivers it later."""
    try:
        queue.enqueue(job.id, job.kind)
    except QueueUnavailable:
        logger.warning("job %s stays queued until the next sweep", job.id)


@lru_cache
def _rq() -> RQJobQueue:
    settings = get_settings()
    return RQJobQueue(settings.redis_url, settings.job_queue_name)


def get_job_queue() -> JobQueue:
    """FastAPI dependency; tests override it with an InlineQueue."""
    return _rq()

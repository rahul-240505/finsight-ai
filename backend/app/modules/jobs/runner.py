"""Run one job by id: claim it, call its handler, record the outcome.

Error policy:
* transient (model, search index or database unreachable) → back to the queue, retried by
  the worker up to `job_max_attempts`, then failed;
* the job's own time limit → failed (it would most likely time out again);
* expected errors (invalid CSV/PDF, missing dataset, no active model) → failed with the
  error's safe code and message;
* anything else → failed as `internal_error`; details go to the log only.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from rq.timeouts import JobTimeoutException
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Job, User
from app.db.session import get_sessionmaker
from app.modules.jobs import service as jobs
from app.modules.jobs import uploads
from app.services.llm import LLMProvider, ModelUnavailable, get_llm
from app.services.vector_store import QdrantStore, VectorStoreUnavailable, get_vector_store

logger = logging.getLogger(__name__)

TRANSIENT = (ModelUnavailable, VectorStoreUnavailable, OperationalError)
MAX_ERROR_ITEMS = 50


class RetryLater(Exception):  # noqa: N818 - a signal to the queue, not an error to report
    """Raised so the queue schedules another attempt; the job row is already back to queued."""


@dataclass
class Deps:
    """Outside services a handler may need; tests pass fakes."""

    llm: LLMProvider = field(default_factory=get_llm)
    store: QdrantStore = field(default_factory=get_vector_store)


Handler = Callable[[Session, User, dict, Deps], dict]


def _handlers() -> dict[str, Handler]:
    # Imported here to keep the module graph acyclic (services import nothing from jobs).
    from app.modules.datasets.service import run_import
    from app.modules.documents.service import run_index
    from app.modules.ml.service import run_scoring

    return {"dataset_import": run_import, "risk_scoring": run_scoring, "document_index": run_index}


def _error(exc: Exception) -> dict:
    if isinstance(exc, AppError):
        extra = {k: v[:MAX_ERROR_ITEMS] if isinstance(v, list) else v for k, v in exc.extra.items()}
        return {"code": exc.code, "message": exc.message, **extra}
    if isinstance(exc, OperationalError):
        return {"code": "database_unavailable", "message": "The database was not reachable."}
    if isinstance(exc, JobTimeoutException):
        return {"code": "job_timeout", "message": "The job took longer than its time limit."}
    return {"code": "internal_error", "message": "The job failed unexpectedly."}


def _finish(job: Job) -> None:
    if name := job.payload.get("upload"):
        uploads.delete(name)


def run_job(job_id: uuid.UUID, db: Session | None = None, deps: Deps | None = None) -> str:
    """Returns the job's status afterwards, or "skipped" if another worker owns it."""
    own_session = db is None
    db = db or get_sessionmaker()()
    try:
        job = jobs.claim(db, job_id)
        if job is None:
            logger.info("job %s skipped: finished or running elsewhere", job_id)
            return "skipped"
        user = db.get(User, job.owner_id)
        logger.info("job %s kind=%s attempt=%d started", job_id, job.kind, job.attempts)
        try:
            if user is None or user.disabled_at is not None:
                raise AppError("The job's owner no longer exists or is disabled.")
            result = _handlers()[job.kind](db, user, job.payload, deps or Deps())
        except TRANSIENT as exc:
            db.rollback()
            job = db.get(Job, job_id, populate_existing=True)
            logger.warning("job %s transient failure: %s", job_id, type(exc).__name__)
            if job.attempts < get_settings().job_max_attempts:
                jobs.release(db, job, _error(exc))
                raise RetryLater(str(job_id)) from exc
            jobs.fail(db, job, _error(exc))
        except Exception as exc:
            db.rollback()
            job = db.get(Job, job_id, populate_existing=True)
            if not isinstance(exc, AppError | JobTimeoutException):
                logger.exception("job %s failed unexpectedly", job_id)
            jobs.fail(db, job, _error(exc))
        else:
            jobs.succeed(db, job, result)
        _finish(job)
        logger.info("job %s kind=%s finished status=%s", job_id, job.kind, job.status)
        return job.status
    finally:
        if own_session:
            db.close()

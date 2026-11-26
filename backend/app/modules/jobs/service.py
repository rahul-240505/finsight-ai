"""Job records (ADR-004). Postgres holds every job's state; the queue only carries job ids.

Life cycle: queued → running → succeeded | failed. A transient failure (model or search
index down, database blip) puts the job back to queued for another attempt, up to
`job_max_attempts`. Every handler is safe to run twice, because delivery is at-least-once:
a worker can crash after finishing the work but before recording it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFound
from app.db.models import Job, User

MAX_PAGE_SIZE = 100
ACTIVE = ("queued", "running")


@dataclass(frozen=True)
class Created:
    job: Job
    created: bool  # False: an unfinished job for the same work already existed


def find_active(db: Session, owner_id: uuid.UUID, kind: str, dedupe_key: str) -> Job | None:
    stmt = select(Job).where(
        Job.owner_id == owner_id,
        Job.kind == kind,
        Job.dedupe_key == dedupe_key,
        Job.status.in_(ACTIVE),
    )
    return db.scalar(stmt)


def add(
    db: Session,
    owner_id: uuid.UUID,
    kind: str,
    dedupe_key: str,
    payload: dict,
    job_id: uuid.UUID | None = None,
) -> Created:
    """Insert a queued job inside the caller's transaction (not committed here).

    If an unfinished job for the same (owner, kind, dedupe_key) exists, return it instead.
    A concurrent insert is caught by the partial unique index `uq_jobs_active_dedupe`.
    """
    if (existing := find_active(db, owner_id, kind, dedupe_key)) is not None:
        return Created(existing, created=False)
    job = Job(
        id=job_id or uuid.uuid4(),
        owner_id=owner_id,
        kind=kind,
        dedupe_key=dedupe_key,
        payload=payload,
    )
    try:
        with db.begin_nested():  # savepoint: a lost race doesn't abort the outer transaction
            db.add(job)
            db.flush()
    except IntegrityError:
        existing = find_active(db, owner_id, kind, dedupe_key)
        if existing is None:
            raise
        return Created(existing, created=False)
    return Created(job, created=True)


def claim(db: Session, job_id: uuid.UUID) -> Job | None:
    """Atomically move a job to running and count the attempt. Returns None if the job is
    finished, or running in another worker that is not yet considered stale.

    The conditional UPDATE is the lock: two workers handed the same id can't both win.
    """
    stale_before = datetime.now(UTC) - timedelta(seconds=get_settings().job_stale_after_seconds)
    stmt = (
        update(Job)
        .where(
            Job.id == job_id,
            or_(
                Job.status == "queued",
                (Job.status == "running") & (Job.started_at < stale_before),
            ),
        )
        .values(status="running", attempts=Job.attempts + 1, started_at=datetime.now(UTC))
        .returning(Job.id)
    )
    claimed = db.execute(stmt).scalar()
    db.commit()
    return db.get(Job, job_id, populate_existing=True) if claimed else None


def succeed(db: Session, job: Job, result: dict) -> None:
    job.status, job.result, job.error = "succeeded", result, None
    job.finished_at = datetime.now(UTC)
    db.commit()


def fail(db: Session, job: Job, error: dict) -> None:
    job.status, job.error = "failed", error
    job.finished_at = datetime.now(UTC)
    db.commit()


def release(db: Session, job: Job, error: dict) -> None:
    """Back to the queue for another attempt; the last error is kept for visibility."""
    job.status, job.error = "queued", error
    db.commit()


def get_owned(db: Session, user: User, job_id: uuid.UUID) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_id == user.id))
    if job is None:
        raise NotFound()
    return job


def list_for(db: Session, user: User, limit: int, offset: int) -> list[Job]:
    stmt = (
        select(Job)
        .where(Job.owner_id == user.id)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(min(limit, MAX_PAGE_SIZE))
        .offset(offset)
    )
    return list(db.scalars(stmt))


def needing_requeue(db: Session, older_than_seconds: int) -> list[Job]:
    """Jobs that may have been lost: still queued after a while (e.g. Redis was down when
    they were enqueued) or running past the stale limit (the worker died)."""
    now = datetime.now(UTC)
    stmt = select(Job).where(
        or_(
            (Job.status == "queued")
            & (Job.created_at < now - timedelta(seconds=older_than_seconds)),
            (Job.status == "running")
            & (Job.started_at < now - timedelta(seconds=get_settings().job_stale_after_seconds)),
        )
    )
    return list(db.scalars(stmt))

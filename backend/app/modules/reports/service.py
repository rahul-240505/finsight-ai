"""Investigation reports: start (queues the agent), read, submit, review.

Visibility: the owner sees their reports. A reviewer (`report:approve`) also sees reports
that were *submitted* for review, from any owner — the one deliberate exception to "only
the owner", because approval needs a second person. Nobody reviews their own report (the
service checks, and the database CHECK `ck_reports_four_eyes` enforces it). State changes
are single conditional UPDATEs, so two reviewers can't both decide the same report.
"""

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound
from app.core.permissions import Permission, has_permission
from app.db.models import AgentStep, Report, User
from app.modules.datasets import service as datasets
from app.modules.idempotency import service as idem
from app.modules.jobs import service as jobs
from app.modules.jobs.schemas import JobOut
from app.worker.queue import JobQueue, enqueue_or_leave_queued

MAX_PAGE_SIZE = 100
REVIEWABLE = ("submitted", "approved", "rejected")


def start_investigation(
    db: Session,
    user: User,
    queue: JobQueue,
    dataset_id: uuid.UUID,
    focus: str,
    key: str,
    request_hash: str,
) -> tuple[int, dict, bool]:
    """Queue an agent run. Same Idempotency-Key → the original 202; the same dataset and
    focus while a run is unfinished → that run's job."""
    record = idem.find(db, user.id, key)
    if record is not None and (replay := idem.check_replay(record, request_hash)):
        return (*replay, True)
    datasets.get_owned(db, user, dataset_id)  # 404 if not yours
    job_id = uuid.uuid4()
    dedupe = hashlib.sha256(f"{dataset_id}:{focus.strip().lower()}".encode()).hexdigest()[:64]
    payload = {"job_id": str(job_id), "dataset_id": str(dataset_id), "focus": focus}
    try:
        record = idem.reserve(db, user.id, key, request_hash)
        created = jobs.add(db, user.id, "investigation", dedupe, payload, job_id)
        body = JobOut.model_validate(created.job).model_dump(mode="json")
        idem.complete(record, 202, body)
        db.commit()
    except IntegrityError:
        db.rollback()
        record = idem.find(db, user.id, key)
        if record is not None and (replay := idem.check_replay(record, request_hash)):
            return (*replay, True)
        raise Conflict("A request with this Idempotency-Key is still being processed.") from None
    if created.created:
        enqueue_or_leave_queued(queue, created.job)
    return 202, body, False


def _can_review(user: User) -> bool:
    return has_permission(user.role, Permission.REPORT_APPROVE)


def list_for(db: Session, user: User, status: str | None, limit: int, offset: int) -> list[Report]:
    visible = Report.owner_id == user.id
    if _can_review(user):
        visible = or_(visible, Report.status.in_(REVIEWABLE))
    stmt = select(Report).where(visible)
    if status:
        stmt = stmt.where(Report.status == status)
    stmt = stmt.order_by(Report.created_at.desc(), Report.id.desc())
    return list(db.scalars(stmt.limit(min(limit, MAX_PAGE_SIZE)).offset(offset)))


def get_visible(db: Session, user: User, report_id: uuid.UUID) -> Report:
    report = db.get(Report, report_id)
    if report is None:
        raise NotFound()
    if report.owner_id == user.id:
        return report
    if _can_review(user) and report.status in REVIEWABLE:
        return report
    raise NotFound()  # drafts of others stay invisible, even to reviewers


def steps_for(db: Session, user: User, report: Report) -> list[AgentStep]:
    if report.job_id is None:
        return []
    stmt = (
        select(AgentStep)
        .where(AgentStep.job_id == report.job_id)
        .order_by(AgentStep.attempt, AgentStep.step)
    )
    return list(db.scalars(stmt))


def submit(db: Session, user: User, report_id: uuid.UUID) -> Report:
    report = get_visible(db, user, report_id)
    if report.owner_id != user.id:
        raise NotFound()
    changed = db.execute(
        update(Report)
        .where(Report.id == report_id, Report.status == "draft")
        .values(status="submitted", submitted_at=datetime.now(UTC))
        .returning(Report.id)
    ).scalar()
    db.commit()
    if changed is None:
        raise Conflict("Only a draft can be submitted.")
    return db.get(Report, report_id, populate_existing=True)


def review(
    db: Session, user: User, report_id: uuid.UUID, approve: bool, note: str | None
) -> Report:
    report = get_visible(db, user, report_id)
    if report.owner_id == user.id:
        raise Forbidden("You can't review your own report.")
    changed = db.execute(
        update(Report)
        .where(Report.id == report_id, Report.status == "submitted", Report.owner_id != user.id)
        .values(
            status="approved" if approve else "rejected",
            reviewed_by=user.id,
            reviewed_at=datetime.now(UTC),
            review_note=note,
        )
        .returning(Report.id)
    ).scalar()
    db.commit()
    if changed is None:
        raise Conflict("Only a submitted report can be reviewed.")
    return db.get(Report, report_id, populate_existing=True)

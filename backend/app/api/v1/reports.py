"""Investigations (agent runs) and their reports. The agent only drafts; people decide."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.deps import DbSession, require_permission
from app.api.v1.jobs import accepted
from app.core.permissions import Permission
from app.core.rate_limit import per_user
from app.db.models import User
from app.modules.idempotency import service as idem
from app.modules.jobs.schemas import JobOut
from app.modules.reports import service
from app.modules.reports.schemas import InvestigationIn, ReportOut, ReviewIn, StepOut
from app.worker.queue import JobQueue, get_job_queue

router = APIRouter(tags=["reports"])

Reader = Annotated[User, Depends(require_permission(Permission.REPORT_READ))]
Writer = Annotated[User, Depends(require_permission(Permission.REPORT_WRITE))]
Reviewer = Annotated[User, Depends(require_permission(Permission.REPORT_APPROVE))]


@router.post(
    "/investigations",
    status_code=202,
    dependencies=[Depends(per_user("investigation"))],
    responses={202: {"model": JobOut, "description": "Agent run queued; result has report_id"}},
)
def start_investigation(
    body: InvestigationIn,
    request: Request,
    db: DbSession,
    user: Writer,
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> JSONResponse:
    """Queue the investigation agent on one of your datasets. Requires `Idempotency-Key`.
    When the job succeeds, its `result.report_id` is a **draft** report."""
    key = idem.require_key(request)
    request_hash = idem.fingerprint(request, body.model_dump_json().encode())
    status_code, job, replayed = service.start_investigation(
        db, user, queue, body.dataset_id, body.focus, key, request_hash
    )
    return accepted(job, {"Idempotent-Replayed": "true"} if replayed else None)


@router.get("/reports")
def list_reports(
    db: DbSession,
    user: Reader,
    status: Annotated[str | None, Query(pattern="^(draft|submitted|approved|rejected)$")] = None,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReportOut]:
    """Your reports; reviewers also see everyone's submitted and reviewed reports."""
    return [ReportOut.model_validate(r) for r in service.list_for(db, user, status, limit, offset)]


@router.get("/reports/{report_id}")
def get_report(report_id: uuid.UUID, db: DbSession, user: Reader) -> ReportOut:
    return ReportOut.model_validate(service.get_visible(db, user, report_id))


@router.get("/reports/{report_id}/steps")
def report_steps(report_id: uuid.UUID, db: DbSession, user: Reader) -> list[StepOut]:
    """The agent's audit trail: every tool call, its validated arguments and outcome."""
    report = service.get_visible(db, user, report_id)
    return [StepOut.model_validate(s) for s in service.steps_for(db, user, report)]


@router.post("/reports/{report_id}/submit")
def submit_report(report_id: uuid.UUID, db: DbSession, user: Writer) -> ReportOut:
    """Send your draft for review (draft → submitted)."""
    return ReportOut.model_validate(service.submit(db, user, report_id))


@router.post("/reports/{report_id}/approve")
def approve_report(
    report_id: uuid.UUID, db: DbSession, user: Reviewer, body: ReviewIn | None = None
) -> ReportOut:
    """Approve someone else's submitted report (`report:approve`; never your own)."""
    note = body.note if body else None
    return ReportOut.model_validate(service.review(db, user, report_id, True, note))


@router.post("/reports/{report_id}/reject")
def reject_report(
    report_id: uuid.UUID, db: DbSession, user: Reviewer, body: ReviewIn | None = None
) -> ReportOut:
    note = body.note if body else None
    return ReportOut.model_validate(service.review(db, user, report_id, False, note))

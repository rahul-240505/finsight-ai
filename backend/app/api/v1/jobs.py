"""Job status. Slow operations answer 202 with a job; clients follow its Location here."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, DbSession
from app.db.models import Job
from app.modules.jobs import service
from app.modules.jobs.schemas import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


def accepted(job: Job | dict, headers: dict[str, str] | None = None) -> JSONResponse:
    """202 Accepted with the job body and a Location header to poll."""
    body = job if isinstance(job, dict) else JobOut.model_validate(job).model_dump(mode="json")
    location = {"Location": f"/api/v1/jobs/{body['id']}"}
    return JSONResponse(body, status.HTTP_202_ACCEPTED, headers=location | (headers or {}))


@router.get("")
def list_jobs(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[JobOut]:
    """Your jobs, newest first. Offset pagination: `limit` (max 100) and `offset`."""
    return [JobOut.model_validate(j) for j in service.list_for(db, user, limit, offset)]


@router.get("/{job_id}")
def get_job(job_id: uuid.UUID, db: DbSession, user: CurrentUser) -> JobOut:
    """Poll until `status` is `succeeded` (see `result`) or `failed` (see `error`)."""
    return JobOut.model_validate(service.get_owned(db, user, job_id))

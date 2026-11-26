"""Dataset routes. Permission checks here; ownership checks in the service.

Uploads send the CSV file as the raw request body (`Content-Type: text/csv`), with the
dataset name in the query string. No multipart parsing library needed.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.api.deps import DbSession, require_permission
from app.api.uploads import read_body
from app.api.v1.jobs import accepted
from app.core.config import get_settings
from app.core.permissions import Permission
from app.core.rate_limit import per_user
from app.db.models import User
from app.modules.datasets import service
from app.modules.datasets.schemas import DatasetOut
from app.modules.idempotency import service as idem
from app.modules.jobs.schemas import JobOut
from app.worker.queue import JobQueue, get_job_queue

router = APIRouter(prefix="/datasets", tags=["datasets"])

Reader = Annotated[User, Depends(require_permission(Permission.DATASET_READ))]
Writer = Annotated[User, Depends(require_permission(Permission.DATASET_WRITE))]
Queue = Annotated[JobQueue, Depends(get_job_queue)]
CSV_TYPES = {"text/csv", "application/csv"}


async def read_csv_body(request: Request) -> bytes:
    return await read_body(request, CSV_TYPES, get_settings().max_upload_bytes)


@router.post("/preview", dependencies=[Depends(per_user("upload"))])
async def preview_import(request: Request, _: Writer) -> dict:
    """Check a CSV without saving anything: row counts, the first 50 errors, sample rows."""
    data = await read_csv_body(request)
    return await run_in_threadpool(service.preview, data)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(per_user("upload"))],
    responses={
        202: {"model": JobOut, "description": "Import queued; follow the Location header"},
        409: {"description": "This file was already imported"},
        422: {"description": "Reused Idempotency-Key"},
        429: {"description": "Too many uploads"},
    },
)
async def import_dataset(
    request: Request,
    db: DbSession,
    user: Writer,
    queue: Queue,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> JSONResponse:
    """Queue a transaction CSV for all-or-nothing import. Requires an `Idempotency-Key`
    header: retrying with the same key and file returns the original job (header
    `Idempotent-Replayed: true`). Row errors appear in the job's `error` when it fails."""
    key = idem.require_key(request)
    data = await read_csv_body(request)
    request_hash = idem.fingerprint(request, data)
    outcome = await run_in_threadpool(
        service.start_import, db, user, queue, name, data, key, request_hash
    )
    headers = {"Idempotent-Replayed": "true"} if outcome.replayed else {}
    if outcome.status_code != status.HTTP_202_ACCEPTED:
        return JSONResponse(outcome.body, outcome.status_code, headers=headers)
    return accepted(outcome.body, headers)


@router.get("")
def list_datasets(
    db: DbSession,
    user: Reader,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DatasetOut]:
    """Offset pagination: `limit` (max 100) and `offset`."""
    return [DatasetOut.model_validate(d) for d in service.list_for(db, user, limit, offset)]


@router.get("/{dataset_id}")
def get_dataset(dataset_id: uuid.UUID, db: DbSession, user: Reader) -> DatasetOut:
    return DatasetOut.model_validate(service.get_owned(db, user, dataset_id))


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: uuid.UUID, db: DbSession, user: Writer) -> None:
    service.delete(db, user, dataset_id)

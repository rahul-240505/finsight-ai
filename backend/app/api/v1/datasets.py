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
from app.core.config import get_settings
from app.core.errors import PayloadTooLarge, UnsupportedMediaType
from app.core.permissions import Permission
from app.db.models import User
from app.modules.datasets import service
from app.modules.datasets.schemas import DatasetOut
from app.modules.idempotency import service as idem

router = APIRouter(prefix="/datasets", tags=["datasets"])

Reader = Annotated[User, Depends(require_permission(Permission.DATASET_READ))]
Writer = Annotated[User, Depends(require_permission(Permission.DATASET_WRITE))]
CSV_TYPES = {"text/csv", "application/csv"}


async def read_csv_body(request: Request) -> bytes:
    """Read the upload with a hard size cap, without trusting Content-Length alone."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in CSV_TYPES:
        raise UnsupportedMediaType("Send the file as the request body with Content-Type: text/csv.")
    limit = get_settings().max_upload_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise PayloadTooLarge(f"The file is larger than {limit} bytes.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise PayloadTooLarge(f"The file is larger than {limit} bytes.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/preview")
async def preview_import(request: Request, _: Writer) -> dict:
    """Check a CSV without saving anything: row counts, the first 50 errors, sample rows."""
    data = await read_csv_body(request)
    return await run_in_threadpool(service.preview, data)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"model": DatasetOut},
        409: {"description": "This file was already imported"},
        422: {"description": "Invalid CSV or reused Idempotency-Key"},
    },
)
async def import_dataset(
    request: Request,
    db: DbSession,
    user: Writer,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> JSONResponse:
    """Import a transaction CSV, all-or-nothing. Requires an `Idempotency-Key` header:
    retrying with the same key and file returns the original result (header
    `Idempotent-Replayed: true`) instead of importing twice."""
    key = idem.require_key(request)
    data = await read_csv_body(request)
    request_hash = idem.fingerprint(request, data)
    # Parsing and COPY are blocking work: run them off the event loop.
    outcome = await run_in_threadpool(service.import_csv, db, user, name, data, key, request_hash)
    headers = {"Idempotent-Replayed": "true"} if outcome.replayed else {}
    return JSONResponse(outcome.body, outcome.status_code, headers=headers)


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

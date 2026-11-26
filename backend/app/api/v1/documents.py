"""Document routes. Upload the PDF as the raw request body (`Content-Type: application/pdf`)."""

import re
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
from app.modules.documents import service
from app.modules.documents.schemas import DocumentOut
from app.modules.jobs.schemas import JobOut
from app.services.vector_store import QdrantStore, get_vector_store
from app.worker.queue import JobQueue, enqueue_or_leave_queued, get_job_queue

router = APIRouter(prefix="/documents", tags=["documents"])

Reader = Annotated[User, Depends(require_permission(Permission.DOCUMENT_READ))]
Writer = Annotated[User, Depends(require_permission(Permission.DOCUMENT_WRITE))]
Queue = Annotated[JobQueue, Depends(get_job_queue)]
Store = Annotated[QdrantStore, Depends(get_vector_store)]
_UNSAFE_NAME = re.compile(r"[^\w .()\-]+")


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(per_user("upload"))],
    responses={
        202: {"model": JobOut, "description": "Indexing queued; follow the Location header"},
        200: {"model": DocumentOut, "description": "This file was already uploaded"},
        422: {"description": "Not a PDF (other problems appear in the job's error)"},
        429: {"description": "Too many uploads"},
    },
)
async def upload_document(
    request: Request,
    db: DbSession,
    user: Writer,
    queue: Queue,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> JSONResponse:
    """Upload a PDF and queue it for indexing. Idempotent by content: the same file again
    returns the existing document (200, `Idempotent-Replayed: true`), or the job already
    indexing it (202)."""
    data = await read_body(request, {"application/pdf"}, get_settings().max_pdf_bytes)
    filename = _UNSAFE_NAME.sub("_", name).strip() or "document.pdf"
    outcome = await run_in_threadpool(service.start_index, db, user, filename, data)
    if outcome.document is not None:
        body = DocumentOut.model_validate(outcome.document).model_dump(mode="json")
        return JSONResponse(body, status.HTTP_200_OK, headers={"Idempotent-Replayed": "true"})
    if outcome.created:
        await run_in_threadpool(enqueue_or_leave_queued, queue, outcome.job)
    return accepted(outcome.job)


@router.get("")
def list_documents(
    db: DbSession,
    user: Reader,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentOut]:
    """Offset pagination: `limit` (max 100) and `offset`, newest first."""
    return [DocumentOut.model_validate(d) for d in service.list_for(db, user, limit, offset)]


@router.get("/{document_id}")
def get_document(document_id: uuid.UUID, db: DbSession, user: Reader) -> DocumentOut:
    return DocumentOut.model_validate(service.get_owned(db, user, document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: uuid.UUID, db: DbSession, user: Writer, store: Store) -> None:
    """Deletes the text and chunks, then the vectors."""
    service.delete(db, user, store, document_id)

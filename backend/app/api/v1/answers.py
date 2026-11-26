"""Questions about the user's documents, answered with page citations."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_permission
from app.core.permissions import Permission
from app.db.models import User
from app.modules.rag import service
from app.modules.rag.schemas import AnswerOut, CitationOut, QuestionIn
from app.services.llm import LLMProvider, get_llm
from app.services.vector_store import QdrantStore, get_vector_store

router = APIRouter(prefix="/answers", tags=["answers"])

Reader = Annotated[User, Depends(require_permission(Permission.DOCUMENT_READ))]


@router.post("")
def ask(
    body: QuestionIn,
    db: DbSession,
    user: Reader,
    llm: Annotated[LLMProvider, Depends(get_llm)],
    store: Annotated[QdrantStore, Depends(get_vector_store)],
) -> AnswerOut:
    """Answer from your own documents only. `status` is `not_enough_evidence` (with a
    `reason`) when no passage is relevant enough or the model's answer has no valid citation."""
    result = service.answer(db, user, llm, store, body.question, body.top_k, body.document_ids)
    return AnswerOut(
        status=result.status,
        answer=result.answer,
        reason=result.reason,
        citations=[
            CitationOut(
                source=p.source_id,
                document_id=p.document_id,
                filename=p.filename,
                page=p.page,
                chunk_id=p.chunk_id,
                excerpt=p.text[: service.EXCERPT_CHARS],
                score=round(p.score, 4),
            )
            for p in result.citations
        ],
        retrieved=len(result.passages),
        model=result.model,
        prompt_version=service.PROMPT_VERSION,
        latency_ms=round(result.latency_ms, 1),
    )

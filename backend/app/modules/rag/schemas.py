import uuid

from pydantic import BaseModel, Field


class QuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    # Limit the search to these documents (all must be yours). Omit to search all of them.
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    top_k: int | None = Field(default=None, ge=1, le=10)


class CitationOut(BaseModel):
    source: str
    document_id: uuid.UUID
    filename: str
    page: int
    chunk_id: uuid.UUID
    excerpt: str
    score: float


class AnswerOut(BaseModel):
    status: str  # "answered" | "not_enough_evidence"
    answer: str | None
    reason: str | None
    citations: list[CitationOut]
    retrieved: int
    model: str | None
    prompt_version: str
    latency_ms: float

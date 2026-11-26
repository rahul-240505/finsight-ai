import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InvestigationIn(BaseModel):
    dataset_id: uuid.UUID
    focus: str = Field(
        default="Review the most unusual transactions and the policies that apply.",
        min_length=3,
        max_length=500,
    )


class ReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt: int
    step: int
    tool: str
    arguments: dict[str, Any] | None
    status: str
    error: str | None
    result_chars: int
    latency_ms: float


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    dataset_id: uuid.UUID
    job_id: uuid.UUID | None
    status: str
    focus: str
    content: dict[str, Any]
    model: str
    prompt_version: str
    created_at: datetime
    submitted_at: datetime | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_note: str | None

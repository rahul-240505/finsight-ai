"""Risk scoring routes. Scores flag *unusual* activity for human review; they don't detect fraud."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import DbSession, require_permission
from app.api.v1.jobs import accepted
from app.core.permissions import Permission
from app.core.rate_limit import per_user
from app.db.models import User
from app.modules.jobs.schemas import JobOut
from app.modules.ml import service
from app.worker.queue import JobQueue, enqueue_or_leave_queued, get_job_queue

router = APIRouter(tags=["risk"])

Reader = Annotated[User, Depends(require_permission(Permission.DATASET_READ))]
Writer = Annotated[User, Depends(require_permission(Permission.DATASET_WRITE))]
Queue = Annotated[JobQueue, Depends(get_job_queue)]


class ScoreRequest(BaseModel):
    dataset_id: uuid.UUID


class ScoreResult(BaseModel):
    dataset_id: uuid.UUID
    model_version: str
    threshold: float
    scored: int
    flagged: int
    flag_rate: float


class AssessmentOut(BaseModel):
    transaction_id: uuid.UUID
    external_ref: str
    account_id: str
    occurred_at: datetime
    amount: Decimal
    currency: str
    merchant: str
    category: str
    risk_score: float  # percentile vs. training data: 0.99 = more unusual than 99% of it
    is_flagged: bool
    reasons: list[str]


class RiskOut(BaseModel):
    transaction_id: uuid.UUID
    risk_score: float
    is_flagged: bool
    reasons: list[str]
    scored_at: datetime


@router.post(
    "/risk-assessments",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(per_user("scoring"))],
    responses={202: {"model": JobOut, "description": "Scoring queued; result is a ScoreResult"}},
)
def score_dataset(body: ScoreRequest, db: DbSession, user: Writer, queue: Queue) -> JSONResponse:
    """Queue scoring of every transaction in a dataset with the active model (replaces
    earlier scores). A dataset already being scored returns that job instead of a new one."""
    created = service.start_scoring(db, user, body.dataset_id)
    if created.created:
        enqueue_or_leave_queued(queue, created.job)
    return accepted(created.job)


@router.get("/risk-assessments")
def list_assessments(
    db: DbSession,
    user: Reader,
    dataset_id: uuid.UUID,
    flagged_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PAGE_SIZE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AssessmentOut]:
    """Review queue, highest risk first. Offset pagination: `limit` (max 100) and `offset`."""
    rows = service.list_assessments(db, user, dataset_id, flagged_only, limit, offset)
    return [
        AssessmentOut(
            transaction_id=t.id,
            external_ref=t.external_ref,
            account_id=t.account_id,
            occurred_at=t.occurred_at,
            amount=t.amount,
            currency=t.currency,
            merchant=t.merchant,
            category=t.category,
            risk_score=round(a.risk_score, 6),
            is_flagged=a.is_flagged,
            reasons=a.reasons,
        )
        for a, t in rows
    ]


@router.get("/transactions/{transaction_id}/risk")
def transaction_risk(transaction_id: uuid.UUID, db: DbSession, user: Reader) -> RiskOut:
    a = service.get_for_transaction(db, user, transaction_id)
    return RiskOut(
        transaction_id=a.transaction_id,
        risk_score=round(a.risk_score, 6),
        is_flagged=a.is_flagged,
        reasons=a.reasons,
        scored_at=a.created_at,
    )

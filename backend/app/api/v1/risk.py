"""Risk scoring routes. Scores flag *unusual* activity for human review; they don't detect fraud."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.api.deps import DbSession, require_permission
from app.core.permissions import Permission
from app.db.models import User
from app.modules.ml import service

router = APIRouter(tags=["risk"])

Reader = Annotated[User, Depends(require_permission(Permission.DATASET_READ))]
Writer = Annotated[User, Depends(require_permission(Permission.DATASET_WRITE))]


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


@router.post("/risk-assessments")
async def score_dataset(body: ScoreRequest, db: DbSession, user: Writer) -> ScoreResult:
    """Score every transaction in a dataset with the active model (replaces earlier scores)."""
    result = await run_in_threadpool(service.score_dataset, db, user, body.dataset_id)
    return ScoreResult(**result)


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

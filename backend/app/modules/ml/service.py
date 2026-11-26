"""Score a dataset with the active risk model and read the results back.

Scores and flags mean "unusual for this account, worth a human look", never "fraud".
"""

import uuid

import pandas as pd
from psycopg.types.json import Jsonb
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.db.models import RiskAssessment, Transaction, User
from app.modules.datasets import service as datasets
from app.modules.jobs import service as jobs
from app.modules.ml import registry
from app.modules.ml.features import build_features, explain

MODEL_NAME = "isolation_forest"
MAX_PAGE_SIZE = 100
COLUMNS = ["id", "account_id", "occurred_at", "amount", "merchant", "category"]
COPY_SQL = (
    "COPY risk_assessments (id, transaction_id, owner_id, dataset_id, model_version_id, "
    "risk_score, is_flagged, reasons) FROM STDIN"
)


def score_dataset(db: Session, user: User, dataset_id: uuid.UUID) -> dict:
    """(Re)score every transaction in one of the user's datasets with the active model.

    Re-running replaces this model's previous scores for the dataset, so it is safe to retry.
    """
    dataset = datasets.get_owned(db, user, dataset_id)  # 404 if missing or not theirs
    version = registry.active_version(db, MODEL_NAME)
    model = registry.load_model(version)
    stmt = select(*(getattr(Transaction, c) for c in COLUMNS)).where(
        Transaction.owner_id == user.id, Transaction.dataset_id == dataset.id
    )
    df = pd.DataFrame(db.execute(stmt).all(), columns=COLUMNS)
    owner_id, version_id, threshold = user.id, version.id, version.threshold
    version_name = version.version
    db.rollback()  # end the read transaction before CPU-heavy scoring

    features = build_features(df) if len(df) else pd.DataFrame()
    scores = model.risk_score(features) if len(df) else []
    flagged = [bool(s >= threshold) for s in scores]

    db.execute(
        delete(RiskAssessment).where(
            RiskAssessment.dataset_id == dataset_id,
            RiskAssessment.model_version_id == version_id,
        )
    )
    raw = db.connection().connection.driver_connection
    with raw.cursor() as cur, cur.copy(COPY_SQL) as copy:
        for i, tx_id in enumerate(df["id"] if len(df) else []):
            reasons = explain(features.iloc[i], df["occurred_at"].iloc[i]) if flagged[i] else []
            copy.write_row(
                (
                    uuid.uuid4(),
                    tx_id,
                    owner_id,
                    dataset_id,
                    version_id,
                    float(scores[i]),
                    flagged[i],
                    Jsonb(reasons),
                )
            )
    db.commit()
    n_flagged = sum(flagged)
    return {
        "dataset_id": str(dataset_id),
        "model_version": version_name,
        "threshold": threshold,
        "scored": len(df),
        "flagged": n_flagged,
        "flag_rate": round(n_flagged / len(df), 4) if len(df) else 0.0,
    }


def list_assessments(
    db: Session, user: User, dataset_id: uuid.UUID, flagged_only: bool, limit: int, offset: int
) -> list[tuple[RiskAssessment, Transaction]]:
    """Review queue: highest risk first, from the active model, owner-scoped.

    Offset pagination: analysts work through the top of the queue (a few thousand rows at most).
    """
    datasets.get_owned(db, user, dataset_id)
    version = registry.active_version(db, MODEL_NAME)
    stmt = (
        select(RiskAssessment, Transaction)
        .join(Transaction, Transaction.id == RiskAssessment.transaction_id)
        .where(
            RiskAssessment.owner_id == user.id,
            RiskAssessment.dataset_id == dataset_id,
            RiskAssessment.model_version_id == version.id,
        )
        .order_by(RiskAssessment.risk_score.desc(), RiskAssessment.id)
        .limit(min(limit, MAX_PAGE_SIZE))
        .offset(offset)
    )
    if flagged_only:
        stmt = stmt.where(RiskAssessment.is_flagged)
    return [(a, t) for a, t in db.execute(stmt).all()]


def get_for_transaction(db: Session, user: User, transaction_id: uuid.UUID) -> RiskAssessment:
    version = registry.active_version(db, MODEL_NAME)
    stmt = select(RiskAssessment).where(
        RiskAssessment.transaction_id == transaction_id,
        RiskAssessment.owner_id == user.id,
        RiskAssessment.model_version_id == version.id,
    )
    assessment = db.scalar(stmt)
    if assessment is None:
        raise NotFound("No risk assessment for this transaction yet.")
    return assessment


def start_scoring(db: Session, user: User, dataset_id: uuid.UUID) -> jobs.Created:
    """Check what can be checked quickly (dataset is yours: 404; a model is active: 409),
    then queue the scoring job. A dataset already being scored joins that job."""
    datasets.get_owned(db, user, dataset_id)
    registry.active_version(db, MODEL_NAME)
    created = jobs.add(
        db, user.id, "risk_scoring", str(dataset_id), {"dataset_id": str(dataset_id)}
    )
    db.commit()
    return created


def run_scoring(db: Session, user: User, payload: dict, deps: object) -> dict:
    """Worker side. Re-running replaces the previous scores, so a repeated delivery is safe."""
    return score_dataset(db, user, uuid.UUID(payload["dataset_id"]))

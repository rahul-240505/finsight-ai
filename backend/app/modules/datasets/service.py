"""Dataset rules. Every function takes the current user and only ever touches their rows.

The ownership filter lives in the query itself (WHERE owner_id = :user), not in a check
after loading, so there is no code path that loads someone else's dataset by accident.
"""

import hashlib
import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, NotFound
from app.db.models import Dataset, User
from app.modules.datasets.schemas import DatasetOut
from app.modules.idempotency import service as idem
from app.modules.transactions.validation import InvalidCsv, ValidRow, parse_csv

MAX_PAGE_SIZE = 100
PREVIEW_SAMPLE_ROWS = 5
COPY_SQL = (
    "COPY transactions (id, dataset_id, owner_id, external_ref, account_id, occurred_at, "
    "amount, currency, merchant, category) FROM STDIN"
)


@dataclass(frozen=True)
class ImportOutcome:
    status_code: int
    body: dict
    replayed: bool


def preview(data: bytes) -> dict:
    """Validate without saving anything: counts, the first errors and a few parsed rows."""
    result = parse_csv(data, get_settings().max_import_rows)
    return {
        "total_rows": result.total_rows,
        "valid_rows": len(result.rows),
        "invalid_rows": result.error_count,
        "errors": [asdict(e) for e in result.errors],
        "sample": [
            {**asdict(r), "amount": str(r.amount), "occurred_at": r.occurred_at.isoformat()}
            for r in result.rows[:PREVIEW_SAMPLE_ROWS]
        ],
    }


def import_csv(
    db: Session, user: User, name: str, data: bytes, key: str, request_hash: str
) -> ImportOutcome:
    """All-or-nothing import (ADR-008): either every row is saved or none is."""
    record = idem.find(db, user.id, key)
    if record is not None and (replay := idem.check_replay(record, request_hash)):
        return ImportOutcome(*replay, replayed=True)

    content_hash = hashlib.sha256(data).hexdigest()
    _reject_duplicate_file(db, user, content_hash)
    db.rollback()  # end the read transaction: never hold one open during CPU-heavy parsing

    result = parse_csv(data, get_settings().max_import_rows)
    if result.error_count:
        raise InvalidCsv(
            f"{result.error_count} of {result.total_rows} rows failed validation. "
            "Nothing was imported.",
            error_count=result.error_count,
            errors=[asdict(e) for e in result.errors],
        )

    try:
        record = idem.reserve(db, user.id, key, request_hash)
        dataset = Dataset(
            owner_id=user.id, name=name, row_count=len(result.rows), content_hash=content_hash
        )
        db.add(dataset)
        db.flush()
        _copy_rows(db, dataset, result.rows)
        db.refresh(dataset)  # server defaults (status, created_at)
        body = DatasetOut.model_validate(dataset).model_dump(mode="json")
        idem.complete(record, 201, body)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        return _resolve_race(db, user, key, request_hash, content_hash, exc)
    return ImportOutcome(201, body, replayed=False)


def _reject_duplicate_file(db: Session, user: User, content_hash: str) -> None:
    stmt = select(Dataset.id).where(
        Dataset.owner_id == user.id, Dataset.content_hash == content_hash
    )
    existing = db.scalar(stmt)
    if existing is not None:
        raise Conflict("This file was already imported.", dataset_id=str(existing))


def _copy_rows(db: Session, dataset: Dataset, rows: list[ValidRow]) -> None:
    """Bulk insert with Postgres COPY, inside the session's transaction. Far faster than
    row-by-row INSERTs, and it rolls back with everything else on failure."""
    raw = db.connection().connection.driver_connection  # the underlying psycopg connection
    with raw.cursor() as cur, cur.copy(COPY_SQL) as copy:
        for r in rows:
            copy.write_row(
                (
                    uuid.uuid4(),
                    dataset.id,
                    dataset.owner_id,
                    r.external_ref,
                    r.account_id,
                    r.occurred_at,
                    r.amount,
                    r.currency,
                    r.merchant,
                    r.category,
                )
            )


def _resolve_race(
    db: Session, user: User, key: str, request_hash: str, content_hash: str, exc: IntegrityError
) -> ImportOutcome:
    """A concurrent request won the race. The database constraints said who; answer
    as if this request had arrived second."""
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint == "uq_idempotency_user_key":
        record = idem.find(db, user.id, key)
        if record is not None and (replay := idem.check_replay(record, request_hash)):
            return ImportOutcome(*replay, replayed=True)
        raise Conflict("A request with this Idempotency-Key is still being processed.")
    if constraint == "uq_datasets_owner_content":
        _reject_duplicate_file(db, user, content_hash)
    raise exc


def list_for(db: Session, user: User, limit: int, offset: int) -> list[Dataset]:
    """Offset pagination is fine here: a user has few datasets. Newest first, id breaks ties."""
    stmt = (
        select(Dataset)
        .where(Dataset.owner_id == user.id)
        .order_by(Dataset.created_at.desc(), Dataset.id.desc())
        .limit(min(limit, MAX_PAGE_SIZE))
        .offset(offset)
    )
    return list(db.scalars(stmt))


def get_owned(db: Session, user: User, dataset_id: uuid.UUID) -> Dataset:
    """404 whether the dataset doesn't exist or belongs to someone else (IDOR protection)."""
    stmt = select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == user.id)
    dataset = db.scalar(stmt)
    if dataset is None:
        raise NotFound()
    return dataset


def delete(db: Session, user: User, dataset_id: uuid.UUID) -> None:
    """Its transactions go too (ON DELETE CASCADE)."""
    db.delete(get_owned(db, user, dataset_id))
    db.commit()

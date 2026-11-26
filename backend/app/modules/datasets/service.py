"""Dataset rules. Every function takes the current user and only ever touches their rows.

The ownership filter lives in the query itself (WHERE owner_id = :user), not in a check
after loading, so there is no code path that loads someone else's dataset by accident.
"""

import hashlib
import logging
import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, NotFound
from app.db.models import Dataset, User
from app.modules.idempotency import service as idem
from app.modules.jobs import service as jobs
from app.modules.jobs import uploads
from app.modules.jobs.schemas import JobOut
from app.modules.transactions.validation import InvalidCsv, ValidRow, parse_csv
from app.worker.queue import JobQueue, enqueue_or_leave_queued

logger = logging.getLogger(__name__)

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


def start_import(
    db: Session,
    user: User,
    queue: JobQueue,
    name: str,
    data: bytes,
    key: str,
    request_hash: str,
) -> ImportOutcome:
    """Accept an import and queue it (ADR-004, ADR-008). Responds 202 with the job.

    Checked now (cheap): the Idempotency-Key, and whether this file was already imported.
    Checked by the worker: every row. An identical file already being imported joins that
    job instead of starting another.
    """
    record = idem.find(db, user.id, key)
    if record is not None and (replay := idem.check_replay(record, request_hash)):
        return ImportOutcome(*replay, replayed=True)
    content_hash = hashlib.sha256(data).hexdigest()
    _reject_duplicate_file(db, user, content_hash)

    saved = None
    try:
        record = idem.reserve(db, user.id, key, request_hash)
        job_id = uuid.uuid4()
        payload = {"name": name, "content_hash": content_hash, "upload": f"{job_id}.csv"}
        created = jobs.add(db, user.id, "dataset_import", content_hash, payload, job_id)
        if created.created:
            saved = uploads.save(job_id, "csv", data)
        body = JobOut.model_validate(created.job).model_dump(mode="json")
        idem.complete(record, 202, body)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if saved:
            uploads.delete(saved)
        return _resolve_race(db, user, key, request_hash, content_hash, exc)
    except Exception:
        db.rollback()
        if saved:
            uploads.delete(saved)
        raise
    if created.created:
        enqueue_or_leave_queued(queue, created.job)
    return ImportOutcome(202, body, replayed=False)


def run_import(db: Session, user: User, payload: dict, deps: object) -> dict:
    """Worker side: validate every row, then insert all of them or none (one transaction)."""
    content_hash = payload["content_hash"]
    existing = db.scalar(
        select(Dataset).where(Dataset.owner_id == user.id, Dataset.content_hash == content_hash)
    )
    if existing is not None:  # a previous attempt finished the work but not the bookkeeping
        return {"dataset_id": str(existing.id), "row_count": existing.row_count}
    data = uploads.read(payload["upload"])
    db.rollback()  # never hold a transaction open during CPU-heavy parsing

    result = parse_csv(data, get_settings().max_import_rows)
    if result.error_count:
        raise InvalidCsv(
            f"{result.error_count} of {result.total_rows} rows failed validation. "
            "Nothing was imported.",
            error_count=result.error_count,
            errors=[asdict(e) for e in result.errors],
        )
    dataset = Dataset(
        owner_id=user.id,
        name=payload["name"],
        row_count=len(result.rows),
        content_hash=content_hash,
    )
    db.add(dataset)
    db.flush()
    _copy_rows(db, dataset, result.rows)
    db.commit()
    return {"dataset_id": str(dataset.id), "row_count": dataset.row_count}


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

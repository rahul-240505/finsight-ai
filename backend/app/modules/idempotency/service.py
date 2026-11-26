"""Idempotency keys (ADR-008): a retried request returns the first response instead of
repeating the work.

Flow for a request with `Idempotency-Key: K` from user U:
1. `find(U, K)`. If a finished record exists: same request fingerprint → replay its response;
   different fingerprint → 422 (the key was reused for a different request).
2. Otherwise, inside the same database transaction as the real work: `reserve(U, K)` inserts
   the record first. UNIQUE(user_id, key) makes a concurrent duplicate wait on that row and
   then fail, so only one of them does the work.
3. `complete(...)` stores the response; everything commits together. If the work fails, the
   whole transaction rolls back, the key is released, and the client may retry.
"""

import hashlib
import re
import uuid

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import IdempotencyRecord

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


class IdempotencyKeyRequired(AppError):
    status_code, code = 400, "idempotency_key_required"
    message = "Send an Idempotency-Key header (1-200 characters: letters, digits, . _ : -)."


class IdempotencyKeyReused(AppError):
    status_code, code = 422, "idempotency_key_reused"
    message = "This Idempotency-Key was already used for a different request."


def require_key(request: Request) -> str:
    key = request.headers.get("idempotency-key", "")
    if not _KEY_PATTERN.match(key):
        raise IdempotencyKeyRequired()
    return key


def fingerprint(request: Request, body: bytes) -> str:
    """Same method + path + query + body → same fingerprint."""
    digest = hashlib.sha256()
    for part in (request.method, request.url.path, request.url.query):
        digest.update(part.encode() + b"\0")
    digest.update(body)
    return digest.hexdigest()


def find(db: Session, user_id: uuid.UUID, key: str) -> IdempotencyRecord | None:
    stmt = select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user_id, IdempotencyRecord.key == key
    )
    return db.scalar(stmt)


def check_replay(record: IdempotencyRecord, request_hash: str) -> tuple[int, dict] | None:
    """The saved (status, body) to replay, or None if the record isn't finished."""
    if record.request_hash != request_hash:
        raise IdempotencyKeyReused()
    if record.status_code is None or record.response_body is None:
        return None
    return record.status_code, record.response_body


def reserve(db: Session, user_id: uuid.UUID, key: str, request_hash: str) -> IdempotencyRecord:
    record = IdempotencyRecord(user_id=user_id, key=key, request_hash=request_hash)
    db.add(record)
    db.flush()  # INSERT now: a concurrent duplicate blocks here, then hits UNIQUE
    return record


def complete(record: IdempotencyRecord, status_code: int, body: dict) -> None:
    record.status_code = status_code
    record.response_body = body

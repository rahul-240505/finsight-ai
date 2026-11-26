"""Document rules: upload, index, list, delete. Every function filters by the current user.

Indexing order (ADR-009), chosen so no database transaction is open during slow work:
1. Same bytes already uploaded by this user → return that document (idempotent by content).
2. Extract and chunk the PDF, then embed every chunk. No transaction is open.
3. Insert the document (status "indexing") and its chunks; commit.
4. Store the vectors in Qdrant. On failure, delete the rows again so nothing half-made remains.
5. Mark the document "ready". Search only ever returns chunks of ready documents.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFound
from app.db.models import Document, DocumentChunk, User
from app.modules.documents.chunking import CHUNKER_VERSION, chunk_pages
from app.modules.documents.pdf import extract_pages
from app.services.llm import LLMProvider, ModelUnavailable
from app.services.vector_store import QdrantStore, VectorPoint, VectorStoreUnavailable

logger = logging.getLogger(__name__)
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class IngestOutcome:
    document: Document
    created: bool


def _by_hash(db: Session, user: User, content_hash: str) -> Document | None:
    stmt = select(Document).where(
        Document.owner_id == user.id, Document.content_hash == content_hash
    )
    return db.scalar(stmt)


def ingest(
    db: Session, user: User, llm: LLMProvider, store: QdrantStore, filename: str, data: bytes
) -> IngestOutcome:
    settings = get_settings()
    content_hash = hashlib.sha256(data).hexdigest()
    if (existing := _by_hash(db, user, content_hash)) is not None:
        return IngestOutcome(existing, created=False)
    db.rollback()  # no transaction open while parsing and embedding

    pages = extract_pages(data, settings.max_pdf_pages)
    chunks = chunk_pages(pages, settings.chunk_max_words, settings.chunk_overlap_words)
    vectors = llm.embed([c.text for c in chunks], "document")
    if len(vectors) != len(chunks) or any(len(v) != settings.embed_dim for v in vectors):
        logger.error("embedding count or size mismatch for model %s", llm.embed_model)
        raise ModelUnavailable("The embedding model returned unexpected output.")

    document = Document(
        owner_id=user.id,
        filename=filename,
        content_hash=content_hash,
        size_bytes=len(data),
        page_count=len(pages),
        chunk_count=len(chunks),
        embedding_model=llm.embed_model,
        chunker_version=CHUNKER_VERSION,
    )
    rows = [
        DocumentChunk(id=uuid.uuid4(), chunk_index=c.index, page=c.page, text=c.text)
        for c in chunks
    ]
    try:
        db.add(document)
        db.flush()
        for row in rows:
            row.document_id, row.owner_id = document.id, user.id
        db.add_all(rows)
        db.commit()
    except IntegrityError:
        # A concurrent upload of the same file won (uq_documents_owner_content).
        db.rollback()
        if (existing := _by_hash(db, user, content_hash)) is not None:
            return IngestOutcome(existing, created=False)
        raise

    points = [
        VectorPoint(row.id, vector, user.id, document.id, row.page)
        for row, vector in zip(rows, vectors, strict=True)
    ]
    try:
        store.upsert(points)
    except Exception:
        db.delete(document)
        db.commit()
        _delete_vectors(store, user.id, document.id)
        raise
    document.status = "ready"
    db.commit()
    db.refresh(document)
    return IngestOutcome(document, created=True)


def _delete_vectors(store: QdrantStore, owner_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """Best effort. Leftover vectors can never be returned: search results are joined back to
    Postgres chunk rows, which are already gone."""
    try:
        store.delete_document(owner_id, document_id)
    except VectorStoreUnavailable:
        logger.warning("vectors not deleted for document %s; orphaned until cleanup", document_id)


def list_for(db: Session, user: User, limit: int, offset: int) -> list[Document]:
    stmt = (
        select(Document)
        .where(Document.owner_id == user.id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(min(limit, MAX_PAGE_SIZE))
        .offset(offset)
    )
    return list(db.scalars(stmt))


def get_owned(db: Session, user: User, document_id: uuid.UUID) -> Document:
    stmt = select(Document).where(Document.id == document_id, Document.owner_id == user.id)
    document = db.scalar(stmt)
    if document is None:
        raise NotFound()
    return document


def delete(db: Session, user: User, store: QdrantStore, document_id: uuid.UUID) -> None:
    """Text first (Postgres, cascades to chunks), then vectors."""
    db.delete(get_owned(db, user, document_id))
    db.commit()
    _delete_vectors(store, user.id, document_id)

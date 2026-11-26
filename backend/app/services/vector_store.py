"""Qdrant adapter over its REST API (ADR-009). Holds vectors and ids only; the chunk text
lives in Postgres, the system of record (ADR-002).

Every search and delete takes an `owner_id` and always filters on it. There is no method that
searches across owners, so a caller can't forget the filter.
"""

import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)


class VectorStoreUnavailable(AppError):
    status_code, code = 503, "vector_store_unavailable"
    message = "The search index is not reachable. Try again later."


@dataclass(frozen=True)
class VectorPoint:
    id: uuid.UUID  # = document_chunks.id
    vector: list[float]
    owner_id: uuid.UUID
    document_id: uuid.UUID
    page: int


@dataclass(frozen=True)
class Hit:
    chunk_id: uuid.UUID
    score: float


def _owner_filter(owner_id: uuid.UUID, document_ids: list[uuid.UUID] | None = None) -> dict:
    must: list[dict] = [{"key": "owner_id", "match": {"value": str(owner_id)}}]
    if document_ids:
        must.append({"key": "document_id", "match": {"any": [str(d) for d in document_ids]}})
    return {"must": must}


class QdrantStore:
    def __init__(self, settings: Settings, collection: str | None = None) -> None:
        self.collection = collection or settings.qdrant_collection
        self.dim = settings.embed_dim
        self._client = httpx.Client(base_url=settings.qdrant_url, timeout=30.0)
        self._ready = False

    def _call(self, method: str, path: str, body: dict | None = None) -> httpx.Response:
        try:
            response = self._client.request(method, path, json=body)
        except httpx.HTTPError as exc:
            logger.warning("qdrant call failed: %s %s", method, type(exc).__name__)
            raise VectorStoreUnavailable() from exc
        if response.status_code >= 500:
            logger.warning("qdrant error: %s %s %d", method, path, response.status_code)
            raise VectorStoreUnavailable()
        return response

    def ensure_collection(self) -> None:
        """Create the collection and its payload indexes once; check the vector size."""
        if self._ready:
            return
        base = f"/collections/{self.collection}"
        found = self._call("GET", base)
        if found.status_code == 404:
            body = {"vectors": {"size": self.dim, "distance": "Cosine"}}
            self._call("PUT", base, body).raise_for_status()
            # is_tenant: Qdrant stores each owner's vectors together, making filtered search fast.
            owner_index = {
                "field_name": "owner_id",
                "field_schema": {"type": "keyword", "is_tenant": True},
            }
            self._call("PUT", f"{base}/index?wait=true", owner_index).raise_for_status()
            doc_index = {"field_name": "document_id", "field_schema": "keyword"}
            self._call("PUT", f"{base}/index?wait=true", doc_index).raise_for_status()
        else:
            found.raise_for_status()
            size = found.json()["result"]["config"]["params"]["vectors"]["size"]
            if size != self.dim:
                raise RuntimeError(
                    f"Collection {self.collection} has {size}-dim vectors, expected {self.dim}. "
                    "The embedding model changed: re-index into a new collection."
                )
        self._ready = True

    def upsert(self, points: list[VectorPoint]) -> None:
        """Idempotent: the point id is the chunk id, so a retry overwrites, never duplicates."""
        self.ensure_collection()
        for i in range(0, len(points), 256):
            body = {
                "points": [
                    {
                        "id": str(p.id),
                        "vector": p.vector,
                        "payload": {
                            "owner_id": str(p.owner_id),
                            "document_id": str(p.document_id),
                            "page": p.page,
                        },
                    }
                    for p in points[i : i + 256]
                ]
            }
            path = f"/collections/{self.collection}/points?wait=true"
            self._call("PUT", path, body).raise_for_status()

    def search(
        self,
        vector: list[float],
        owner_id: uuid.UUID,
        limit: int,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[Hit]:
        self.ensure_collection()
        body = {
            "query": vector,
            "filter": _owner_filter(owner_id, document_ids),
            "limit": limit,
            "with_payload": False,
        }
        response = self._call("POST", f"/collections/{self.collection}/points/query", body)
        response.raise_for_status()
        points = response.json()["result"]["points"]
        return [Hit(uuid.UUID(p["id"]), float(p["score"])) for p in points]

    def delete_document(self, owner_id: uuid.UUID, document_id: uuid.UUID) -> None:
        self.ensure_collection()
        body = {"filter": _owner_filter(owner_id, [document_id])}
        path = f"/collections/{self.collection}/points/delete?wait=true"
        self._call("POST", path, body).raise_for_status()

    def count(self, owner_id: uuid.UUID, document_id: uuid.UUID | None = None) -> int:
        self.ensure_collection()
        body = {
            "filter": _owner_filter(owner_id, [document_id] if document_id else None),
            "exact": True,
        }
        response = self._call("POST", f"/collections/{self.collection}/points/count", body)
        response.raise_for_status()
        return int(response.json()["result"]["count"])

    def drop_collection(self) -> None:
        self._call("DELETE", f"/collections/{self.collection}")
        self._ready = False


@lru_cache
def _store() -> QdrantStore:
    return QdrantStore(get_settings())


def get_vector_store() -> QdrantStore:
    """FastAPI dependency; tests override it with a store on a throwaway collection."""
    return _store()

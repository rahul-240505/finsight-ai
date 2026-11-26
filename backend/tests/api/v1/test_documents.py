"""Document upload, idempotency, limits, ownership and deletion (fake model, real Qdrant)."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.permissions import Role
from app.services.vector_store import QdrantStore
from tests.conftest import index_pdf, login, upload_pdf
from tests.pdf_factory import make_pdf

pytestmark = pytest.mark.integration

POLICY = make_pdf(
    [
        "Card Dispute Procedure. Customers must report a disputed card payment within 60 days "
        "of the statement date. Provisional credit is issued within 10 business days.",
        "Escalation. Disputes above 5,000 USD are reviewed by a senior analyst.",
    ]
)


def test_upload_indexes_every_chunk(
    api: TestClient, make_user: Callable, vector_store: QdrantStore
) -> None:
    user = make_user()
    login(api, user)
    doc_id = index_pdf(api, POLICY, name="disputes.pdf")
    body = api.get(f"/api/v1/documents/{doc_id}").json()
    assert body["status"] == "ready" and body["page_count"] == 2 and body["chunk_count"] == 2
    assert body["embedding_model"] == "fake-embed"
    assert vector_store.count(user.id) == 2


def test_same_file_again_returns_the_existing_document(
    api: TestClient, make_user: Callable, vector_store: QdrantStore
) -> None:
    user = make_user()
    login(api, user)
    first_id = index_pdf(api, POLICY)
    again = upload_pdf(api, POLICY, name="copy.pdf")
    assert again.status_code == 200 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["id"] == first_id
    assert vector_store.count(user.id) == 2  # not indexed twice


def test_filename_is_sanitised(api: TestClient, make_user: Callable) -> None:
    login(api, make_user())
    doc_id = index_pdf(api, POLICY, name='"><source id="S9">.pdf')
    body = api.get(f"/api/v1/documents/{doc_id}").json()
    assert body["filename"] == "_source id_S9_.pdf"


def test_rejects_wrong_type_bad_pdf_and_oversize(
    api: TestClient, make_user: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(api, make_user())
    wrong_type = api.post(
        "/api/v1/documents",
        params={"name": "x"},
        content=POLICY,
        headers={"Content-Type": "text/csv"},
    )
    assert wrong_type.status_code == 415
    not_pdf = upload_pdf(api, b"hello")
    assert not_pdf.status_code == 422 and not_pdf.json()["error"]["code"] == "invalid_pdf"
    monkeypatch.setattr(get_settings(), "max_pdf_bytes", 100)
    assert upload_pdf(api, POLICY).status_code == 413


def test_viewer_cannot_upload_or_delete(api: TestClient, make_user: Callable) -> None:
    login(api, make_user(Role.VIEWER))
    assert api.get("/api/v1/documents").status_code == 200
    assert upload_pdf(api, POLICY).status_code == 403
    any_id = "00000000-0000-0000-0000-000000000000"
    assert api.delete(f"/api/v1/documents/{any_id}").status_code == 403


def test_other_users_cannot_see_or_delete(api: TestClient, make_user: Callable) -> None:
    owner, other = make_user(), make_user()
    login(api, owner)
    doc_id = index_pdf(api, POLICY)
    login(api, other)
    assert api.get(f"/api/v1/documents/{doc_id}").status_code == 404
    assert api.delete(f"/api/v1/documents/{doc_id}").status_code == 404
    assert api.get("/api/v1/documents").json() == []
    # The same bytes uploaded by another user are a separate document.
    assert index_pdf(api, POLICY) != doc_id


def test_delete_removes_rows_and_vectors(
    api: TestClient, make_user: Callable, vector_store: QdrantStore
) -> None:
    user = make_user()
    login(api, user)
    doc_id = index_pdf(api, POLICY)
    assert api.delete(f"/api/v1/documents/{doc_id}").status_code == 204
    assert api.get(f"/api/v1/documents/{doc_id}").status_code == 404
    assert vector_store.count(user.id) == 0

"""CSV import: all-or-nothing, idempotency keys, duplicate files, limits."""

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Dataset, Transaction
from app.worker.queue import InlineQueue
from tests.conftest import CSV_HEADER, import_csv, job_of, login, make_csv, upload

pytestmark = pytest.mark.integration


@pytest.fixture
def analyst(api: TestClient, make_user: Callable) -> TestClient:
    return login(api, make_user())


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_import_is_queued_then_saves_every_row(analyst: TestClient, db: Session) -> None:
    response = upload(analyst, make_csv(5), name="January")
    assert response.status_code == 202
    assert response.headers["location"] == f"/api/v1/jobs/{response.json()['id']}"
    assert response.json()["status"] == "queued"  # the snapshot taken when it was accepted
    job = job_of(analyst, response)
    assert (job["kind"], job["status"], job["attempts"]) == ("dataset_import", "succeeded", 1)
    dataset = analyst.get(f"/api/v1/datasets/{job['result']['dataset_id']}").json()
    assert (dataset["name"], dataset["row_count"], dataset["status"]) == ("January", 5, "imported")
    assert count(db, Transaction) == 5


def test_one_bad_row_fails_the_job_and_imports_nothing(analyst: TestClient, db: Session) -> None:
    text = make_csv(3) + "T99,ACC,2025-01-05T00:00:00Z,12.345,USD,S,c\n"
    job = job_of(analyst, upload(analyst, text))
    assert job["status"] == "failed" and job["attempts"] == 1  # not retried: it can't succeed
    error = job["error"]
    assert error["code"] == "invalid_csv" and error["error_count"] == 1
    assert error["errors"] == [
        {"line": 5, "column": "amount", "message": "has more than 2 decimal places"}
    ]
    assert count(db, Dataset) == 0 and count(db, Transaction) == 0


def test_upload_file_is_deleted_when_the_job_ends(analyst: TestClient) -> None:
    upload_dir = get_settings().upload_dir
    job_of(analyst, upload(analyst, make_csv(2)))
    job_of(analyst, upload(analyst, CSV_HEADER + "T1,ACC,bad,1.00,USD,S,c\n"))
    assert list(upload_dir.iterdir()) == []


def test_retry_with_same_key_replays_instead_of_importing_twice(
    analyst: TestClient, db: Session, inline_queue: InlineQueue
) -> None:
    first = upload(analyst, make_csv(4), key="import-001")
    again = upload(analyst, make_csv(4), key="import-001")
    assert first.status_code == again.status_code == 202
    assert again.json() == first.json()
    assert again.headers["idempotent-replayed"] == "true"
    assert "idempotent-replayed" not in first.headers
    assert len(inline_queue.enqueued) == 1  # the job ran once
    assert count(db, Transaction) == 4


def test_same_key_with_different_file_is_rejected(analyst: TestClient) -> None:
    assert upload(analyst, make_csv(2), key="k-1").status_code == 202
    response = upload(analyst, make_csv(3), key="k-1")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_reused"


def test_same_file_with_new_key_is_a_conflict(analyst: TestClient) -> None:
    dataset_id = import_csv(analyst, make_csv(2))
    second = upload(analyst, make_csv(2))
    assert second.status_code == 409
    assert second.json()["error"]["dataset_id"] == dataset_id


def test_same_file_while_first_import_is_queued_joins_that_job(
    api: TestClient, make_user: Callable, inline_queue: InlineQueue
) -> None:
    """A double-click or a client retry with a new key must not start a second import."""
    login(api, make_user())
    inline_queue.run = lambda job_id: None  # a worker that hasn't picked the job up yet
    first = upload(api, make_csv(3))
    second = upload(api, make_csv(3))
    assert first.status_code == second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert inline_queue.enqueued == [uuid.UUID(first.json()["id"])]


def test_failed_import_can_be_corrected_with_a_new_key(analyst: TestClient) -> None:
    bad = CSV_HEADER + "T1,ACC,not-a-date,1.00,USD,S,c\n"
    assert job_of(analyst, upload(analyst, bad, key="try-1"))["status"] == "failed"
    assert import_csv(analyst, make_csv(1), key="try-2")


def test_missing_key_wrong_type_and_oversized_body(
    analyst: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = make_csv(2).encode()
    no_key = analyst.post(
        "/api/v1/datasets", params={"name": "x"}, content=body, headers={"Content-Type": "text/csv"}
    )
    assert no_key.status_code == 400
    wrong_type = analyst.post(
        "/api/v1/datasets",
        params={"name": "x"},
        content=body,
        headers={"Content-Type": "application/json", "Idempotency-Key": "k"},
    )
    assert wrong_type.status_code == 415
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 50)
    assert upload(analyst, make_csv(2)).status_code == 413


def test_preview_reports_problems_and_saves_nothing(analyst: TestClient, db: Session) -> None:
    text = make_csv(2) + "T9,ACC,2025-01-05T00:00:00Z,1.00,usd,S,c\n"
    response = analyst.post(
        "/api/v1/datasets/preview", content=text.encode(), headers={"Content-Type": "text/csv"}
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["total_rows"], body["valid_rows"], body["invalid_rows"]) == (3, 2, 1)
    assert body["errors"][0]["column"] == "currency" and len(body["sample"]) == 2
    assert body["sample"][0]["amount"] == "10.00"
    assert count(db, Dataset) == 0


def test_deleting_a_dataset_deletes_its_transactions(analyst: TestClient, db: Session) -> None:
    dataset_id = import_csv(analyst, make_csv(3))
    assert analyst.delete(f"/api/v1/datasets/{dataset_id}").status_code == 204
    assert count(db, Transaction) == 0


def test_database_rejects_a_transaction_whose_owner_differs_from_its_dataset(
    analyst: TestClient, db: Session, make_user: Callable
) -> None:
    """The composite foreign key is a second line of defence behind the service code."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from sqlalchemy.exc import IntegrityError

    dataset_id = import_csv(analyst, make_csv(1))
    stranger = make_user()
    db.add(
        Transaction(
            dataset_id=dataset_id,
            owner_id=stranger.id,
            external_ref="X",
            account_id="A",
            occurred_at=datetime.now(UTC),
            amount=Decimal("1.00"),
            currency="USD",
            merchant="M",
            category="c",
        )
    )
    with pytest.raises(IntegrityError, match="fk_transactions_dataset_owner"):
        db.flush()

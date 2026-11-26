"""Risk scoring through the API with a small real model, plus permissions and isolation."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.db.models import ModelVersion, RiskAssessment
from tests.conftest import import_csv, job_of, login

pytestmark = pytest.mark.integration


@pytest.fixture
def scored(
    api: TestClient, make_user: Callable, active_model: ModelVersion, csv_text: str
) -> tuple[TestClient, str]:
    login(api, make_user())
    dataset_id = import_csv(api, csv_text)
    job = job_of(api, api.post("/api/v1/risk-assessments", json={"dataset_id": dataset_id}))
    assert job["kind"] == "risk_scoring" and job["status"] == "succeeded", job
    assert job["result"]["scored"] == 81
    return api, dataset_id


def test_scoring_covers_every_row_and_flags_the_outlier(scored: tuple, db: Session) -> None:
    """Flagged, not necessarily ranked first: Isolation Forest can't rank a point far outside
    the training range above the most extreme training points (see docs/evaluation.md)."""
    api, dataset_id = scored
    queue = api.get("/api/v1/risk-assessments", params={"dataset_id": dataset_id}).json()
    outlier = next(r for r in queue if r["external_ref"] == "OUTLIER")
    assert outlier["is_flagged"]
    assert any("standard deviations" in reason for reason in outlier["reasons"])
    scores = [r["risk_score"] for r in queue]
    assert scores == sorted(scores, reverse=True)
    assert db.scalar(select(func.count()).select_from(RiskAssessment)) == 81


def test_rescoring_replaces_instead_of_duplicating(scored: tuple, db: Session) -> None:
    api, dataset_id = scored
    again = job_of(api, api.post("/api/v1/risk-assessments", json={"dataset_id": dataset_id}))
    assert again["status"] == "succeeded" and again["result"]["scored"] == 81
    assert db.scalar(select(func.count()).select_from(RiskAssessment)) == 81


def test_single_transaction_risk(scored: tuple) -> None:
    api, dataset_id = scored
    queue = api.get("/api/v1/risk-assessments", params={"dataset_id": dataset_id}).json()
    top = next(r for r in queue if r["external_ref"] == "OUTLIER")
    risk = api.get(f"/api/v1/transactions/{top['transaction_id']}/risk").json()
    assert risk["is_flagged"] and risk["reasons"] == top["reasons"]


def test_other_users_cannot_score_or_read(scored: tuple, make_user: Callable) -> None:
    api, dataset_id = scored
    tx_id = api.get(
        "/api/v1/risk-assessments", params={"dataset_id": dataset_id, "flagged_only": False}
    ).json()[0]["transaction_id"]
    login(api, make_user())
    assert api.post("/api/v1/risk-assessments", json={"dataset_id": dataset_id}).status_code == 404
    assert api.get("/api/v1/risk-assessments", params={"dataset_id": dataset_id}).status_code == 404
    assert api.get(f"/api/v1/transactions/{tx_id}/risk").status_code == 404


def test_viewer_can_read_but_not_score_or_delete(
    api: TestClient, make_user: Callable, active_model: ModelVersion, csv_text: str
) -> None:
    owner = make_user(Role.VIEWER)
    login(api, make_user())
    assert import_csv(api, csv_text)
    login(api, owner)
    any_id = "00000000-0000-0000-0000-000000000000"
    assert api.post("/api/v1/risk-assessments", json={"dataset_id": any_id}).status_code == 403
    assert api.delete(f"/api/v1/datasets/{any_id}").status_code == 403
    assert api.get("/api/v1/risk-assessments", params={"dataset_id": any_id}).status_code == 404


def test_no_active_model_is_409(api: TestClient, make_user: Callable, csv_text: str) -> None:
    login(api, make_user())
    dataset_id = import_csv(api, csv_text)
    response = api.post("/api/v1/risk-assessments", json={"dataset_id": dataset_id})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_active_model"

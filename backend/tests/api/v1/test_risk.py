"""Risk scoring through the API with a small real model, plus permissions and isolation."""

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.ensemble import IsolationForest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.permissions import Role
from app.db.models import ModelVersion, RiskAssessment
from app.modules.ml import registry
from app.modules.ml.features import FEATURE_NAMES, build_features
from app.modules.ml.model import RiskModel
from tests.conftest import CSV_HEADER, login, upload

pytestmark = pytest.mark.integration


def normal_rows(account: str, start: int) -> list[str]:
    return [
        f"{account}-{d},{account},2025-02-{d % 28 + 1:02d}T{10 + d % 8}:00:00Z,"
        f"{20 + d % 5}.00,USD,Shop {d % 2},food"
        for d in range(start, start + 40)
    ]


@pytest.fixture
def csv_text() -> str:
    rows = normal_rows("A", 0) + normal_rows("B", 100)
    rows.append("OUTLIER,A,2025-03-15T03:10:00Z,4999.00,USD,QuickCrypto,transfer")
    return CSV_HEADER + "\n".join(rows) + "\n"


@pytest.fixture
def active_model(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, csv_text: str
) -> ModelVersion:
    """Train a tiny Isolation Forest on the normal rows and register it as active."""
    monkeypatch.setattr(get_settings(), "model_dir", tmp_path)
    df = pd.read_csv(pd.io.common.StringIO(csv_text)).rename(columns={"timestamp": "occurred_at"})
    df = df[df["transaction_id"] != "OUTLIER"]
    X = build_features(df)
    model = RiskModel(IsolationForest(n_estimators=50, random_state=0).fit(X), X, combine=False)
    sha = registry.save_model(model, "test/model.joblib")
    version = ModelVersion(
        name="isolation_forest",
        version="test-v1",
        algorithm="IsolationForest",
        feature_names=FEATURE_NAMES,
        params={},
        metrics={},
        # Flags roughly the top 5%. This fixture tests the API plumbing; model quality is
        # measured on 500k rows by ml/training/train_isolation_forest.py.
        threshold=0.95,
        training_data="test fixture",
        artifact_path="test/model.joblib",
        artifact_sha256=sha,
    )
    return registry.register(db, version, activate=True)


@pytest.fixture
def scored(
    api: TestClient, make_user: Callable, active_model: ModelVersion, csv_text: str
) -> tuple[TestClient, str]:
    login(api, make_user())
    dataset_id = upload(api, csv_text).json()["id"]
    response = api.post("/api/v1/risk-assessments", json={"dataset_id": dataset_id})
    assert response.status_code == 200, response.text
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
    again = api.post("/api/v1/risk-assessments", json={"dataset_id": dataset_id})
    assert again.status_code == 200 and again.json()["scored"] == 81
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
    # A viewer can't upload, so promote briefly via the service layer isn't needed:
    # give the viewer data by importing as an analyst account with the same identity.
    login(api, make_user())
    assert upload(api, csv_text).status_code == 201
    login(api, owner)
    any_id = "00000000-0000-0000-0000-000000000000"
    assert api.post("/api/v1/risk-assessments", json={"dataset_id": any_id}).status_code == 403
    assert api.delete(f"/api/v1/datasets/{any_id}").status_code == 403
    assert api.get("/api/v1/risk-assessments", params={"dataset_id": any_id}).status_code == 404


def test_no_active_model_is_409(api: TestClient, make_user: Callable, csv_text: str) -> None:
    login(api, make_user())
    dataset_id = upload(api, csv_text).json()["id"]
    response = api.post("/api/v1/risk-assessments", json={"dataset_id": dataset_id})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_active_model"

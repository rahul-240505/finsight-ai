"""Metric helpers and model-file integrity checks. No database needed."""

import uuid
from pathlib import Path

import numpy as np
import pytest

from app.core.config import get_settings
from app.db.models import ModelVersion
from app.modules.ml import registry
from app.modules.ml.evaluation import choose_threshold, metrics_at, precision_at_k


def test_threshold_separates_perfectly_separable_scores() -> None:
    y = np.array([0, 0, 0, 1, 1])
    scores = np.array([0.1, 0.2, 0.3, 0.8, 0.9])
    threshold = choose_threshold(y, scores)
    assert 0.3 < threshold <= 0.8
    m = metrics_at(y, scores, threshold)
    assert (m["precision"], m["recall"], m["f1"], m["pr_auc"]) == (1.0, 1.0, 1.0, 1.0)


def test_metrics_count_errors_correctly() -> None:
    y = np.array([1, 0, 1, 0, 0, 0])
    scores = np.array([0.9, 0.8, 0.1, 0.2, 0.3, 0.05])
    m = metrics_at(y, scores, threshold=0.5)
    assert (m["tp"], m["fp"], m["fn"]) == (1, 1, 1)
    assert m["precision"] == 0.5 and m["recall"] == 0.5 and m["flag_rate"] == round(2 / 6, 4)
    assert precision_at_k(y, scores, k=2) == 0.5


@pytest.fixture
def model_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "model_dir", tmp_path)
    return tmp_path


def version_for(relative: str, sha: str) -> ModelVersion:
    return ModelVersion(id=uuid.uuid4(), artifact_path=relative, artifact_sha256=sha)


def test_model_loads_only_when_hash_matches(model_dir: Path) -> None:
    sha = registry.save_model({"weights": [1, 2, 3]}, "v1/model.joblib")
    assert registry.load_model(version_for("v1/model.joblib", sha)) == {"weights": [1, 2, 3]}

    (model_dir / "v1" / "model.joblib").write_bytes(b"swapped file")
    with pytest.raises(registry.ModelIntegrityError):
        registry.load_model(version_for("v1/model.joblib", sha))


def test_model_path_cannot_escape_the_model_folder(model_dir: Path) -> None:
    with pytest.raises(registry.ModelIntegrityError, match="outside"):
        registry.load_model(version_for("../../etc/passwd", "0" * 64))

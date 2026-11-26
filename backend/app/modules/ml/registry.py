"""Model registry: save, verify and load model files tracked in `model_versions`.

joblib files are pickles, and loading a pickle can run arbitrary code. So a model is only
loaded if (1) its path stays inside settings.model_dir and (2) its SHA-256 matches the hash
recorded when it was trained. A swapped or corrupted file is refused.
"""

import hashlib
import uuid
from pathlib import Path
from typing import Any

import joblib
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import ModelVersion

_cache: dict[uuid.UUID, Any] = {}  # version id → loaded model (files are immutable once saved)


class NoActiveModel(AppError):
    status_code, code = 409, "no_active_model"
    message = "No active risk model. Train and register one first."


class ModelIntegrityError(AppError):
    status_code, code = 500, "model_integrity_error"
    message = "The model file failed its integrity check and was not loaded."


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(relative: str) -> Path:
    root = get_settings().model_dir.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ModelIntegrityError("Model path is outside the model directory.")
    return path


def save_model(model: Any, relative_path: str) -> str:
    """Write the model file and return its SHA-256."""
    path = _resolve(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    return sha256_file(path)


def register(db: Session, version: ModelVersion, activate: bool) -> ModelVersion:
    """Insert a version; if `activate`, make it the only active one for its name."""
    if activate:
        db.execute(
            update(ModelVersion)
            .where(ModelVersion.name == version.name, ModelVersion.is_active)
            .values(is_active=False)
        )
        version.is_active = True
    db.add(version)
    db.commit()
    return version


def active_version(db: Session, name: str) -> ModelVersion:
    stmt = select(ModelVersion).where(ModelVersion.name == name, ModelVersion.is_active)
    version = db.scalar(stmt)
    if version is None:
        raise NoActiveModel()
    return version


def load_model(version: ModelVersion) -> Any:
    if version.id in _cache:
        return _cache[version.id]
    path = _resolve(version.artifact_path)
    if not path.is_file() or sha256_file(path) != version.artifact_sha256:
        raise ModelIntegrityError()
    model = joblib.load(path)  # safe to unpickle: the file is the one we trained and hashed
    _cache[version.id] = model
    return model

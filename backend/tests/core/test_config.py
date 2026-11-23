import pytest
from pydantic import ValidationError

from app.core.config import Settings

DB_URL = "postgresql+psycopg://u:super-secret@localhost:5433/db"


def test_missing_database_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)  # ignore the developer's real .env


def test_database_url_is_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    settings = Settings(_env_file=None)
    assert "super-secret" not in repr(settings)
    assert settings.database_url.get_secret_value() == DB_URL


def test_rejects_unreasonable_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("READY_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValidationError, match="ready_timeout_seconds"):
        Settings(_env_file=None)

"""Application settings, loaded once from environment variables and the repo-root .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py -> core -> app -> backend -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Typed config. Real env vars override values from .env."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        extra="ignore",  # .env also holds POSTGRES_* vars meant for Docker Compose
    )

    app_env: Literal["local", "test", "ci"] = "local"
    # Required: no default, so a missing value fails at startup, not on the first query.
    database_url: SecretStr
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    ollama_base_url: str = "http://localhost:11434"
    # Model names live only here (ADR-003). Changing the embed model means re-embedding all docs.
    ollama_chat_model: str = "qwen3.5:4b"
    ollama_embed_model: str = "nomic-embed-text"
    # nomic-embed-text expects a task prefix; another embed model may need different ones.
    embed_document_prefix: str = "search_document: "
    embed_query_prefix: str = "search_query: "
    embed_dim: int = Field(default=768, gt=0)
    ollama_timeout_seconds: float = Field(default=120.0, gt=0)
    ollama_num_ctx: int = Field(default=4096, ge=1024)
    ready_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    # Auth (ADR-005): opaque session token in an HttpOnly, Secure, SameSite=Lax cookie.
    session_cookie_name: str = "finsight_session"
    session_ttl_hours: int = Field(default=12, gt=0, le=24 * 30)
    # Browser origins allowed to send state-changing requests (CSRF Origin check).
    allowed_origins: list[str] = ["http://localhost:5173"]

    # CSV import limits (checked before parsing; protects memory and the database).
    max_upload_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    max_import_rows: int = Field(default=1_000_000, gt=0)

    # Trained model files (git-ignored). model_versions stores paths relative to this folder.
    model_dir: Path = REPO_ROOT / "ml" / "artifacts"

    # Documents and question answering (ADR-009).
    qdrant_collection: str = "document_chunks"
    max_pdf_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=200, gt=0)
    # 100/20 beat 200/40 and 350/60 on dev MRR@5 (docs/evaluation.md).
    chunk_max_words: int = Field(default=100, gt=10)
    chunk_overlap_words: int = Field(default=20, ge=0)
    rag_top_k: int = Field(default=5, ge=1, le=10)
    # Below this cosine similarity the best match is treated as unrelated, and the answer is
    # "not enough evidence" without calling the chat model. Specific to the embedding model;
    # set on the eval dev split as the highest value that blocks no answerable question.
    rag_min_score: float = Field(default=0.64, ge=0, le=1)
    rag_max_answer_tokens: int = Field(default=400, gt=0)

    # Background jobs (ADR-004). Uploads wait on disk until the worker has processed them.
    upload_dir: Path = REPO_ROOT / "uploads"
    job_queue_name: str = "finsight"
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    # A "running" job older than this is treated as abandoned (worker crashed) and may be
    # claimed again. Must exceed the longest job timeout.
    job_stale_after_seconds: int = Field(default=1800, gt=0)

    # Rate limits (ADR-007): "<requests>/<seconds>" per bucket, fixed windows in Redis.
    rate_limit_prefix: str = "rl"
    rate_limits: dict[str, str] = {
        "login_ip": "30/60",
        "login_email": "10/300",
        "upload": "20/60",
        "scoring": "10/60",
        "answers": "30/60",
    }


@lru_cache
def get_settings() -> Settings:
    """Parse settings once per process; tests call get_settings.cache_clear() to reload."""
    return Settings()

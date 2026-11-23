"""Dependency checks for the /ready probe. Each check raises on failure and has a hard timeout."""

import logging
import math
from collections.abc import Callable

import httpx
import psycopg
import redis

from app.core.config import Settings

logger = logging.getLogger(__name__)

Check = Callable[[], None]


def build_checks(settings: Settings) -> dict[str, Check]:
    """Real checks against Postgres, Redis and Qdrant, all bounded by ready_timeout_seconds."""
    timeout = settings.ready_timeout_seconds

    def postgres() -> None:
        # SQLAlchemy-style URL -> plain libpq URL for psycopg. libpq timeout is whole seconds.
        url = settings.database_url.get_secret_value().replace(
            "postgresql+psycopg://", "postgresql://"
        )
        with psycopg.connect(url, connect_timeout=max(1, math.ceil(timeout))) as conn:
            conn.execute("SELECT 1")

    def redis_check() -> None:
        client = redis.Redis.from_url(
            settings.redis_url, socket_connect_timeout=timeout, socket_timeout=timeout
        )
        try:
            client.ping()
        finally:
            client.close()

    def qdrant() -> None:
        httpx.get(f"{settings.qdrant_url}/readyz", timeout=timeout).raise_for_status()

    return {"postgres": postgres, "redis": redis_check, "qdrant": qdrant}


def run_checks(checks: dict[str, Check]) -> dict[str, str]:
    """Run every check; report only 'ok'/'down' so error details never reach the client."""
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            check()
            results[name] = "ok"
        except Exception as exc:  # any failure means "not ready"; details go to logs only
            logger.warning("readiness check failed: %s (%s)", name, type(exc).__name__)
            results[name] = "down"
    return results

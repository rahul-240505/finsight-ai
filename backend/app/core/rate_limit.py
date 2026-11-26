"""Fixed-window rate limits in Redis (ADR-007).

For each (bucket, subject, window) there is one counter: INCR it, give it an expiry the first
time, and refuse once it passes the limit. One round trip (a pipeline), atomic per command,
and shared by every API process because it lives in Redis.

Trade-off: a client can send up to 2× the limit across a window boundary (end of one window
+ start of the next). Acceptable for abuse protection; a sliding window costs more.

If Redis is down the limiter fails open (requests pass, a warning is logged): rate limits
here protect capacity, and a Redis outage shouldn't take the API down with it. Failing open
must also be *fast*: the client never retries (redis-py's default retries cost ~4 s per
request against a dead server), and after a failure Redis is skipped for a short cool-down.
"""

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import redis
from fastapi import Depends, Request
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.config import get_settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)


class RateLimited(AppError):
    status_code, code = 429, "rate_limited"
    message = "Too many requests. Try again later."


@dataclass(frozen=True)
class Limit:
    requests: int
    seconds: int

    @classmethod
    def parse(cls, spec: str) -> "Limit":
        requests, seconds = spec.split("/")
        return cls(int(requests), int(seconds))


COOLDOWN_SECONDS = 5.0
_skip_until = 0.0  # while time.monotonic() is below this, don't even try Redis


def make_client(url: str) -> redis.Redis:
    return redis.Redis.from_url(
        url, socket_connect_timeout=0.5, socket_timeout=0.5, retry=Retry(NoBackoff(), 0)
    )


@lru_cache
def _client() -> redis.Redis:
    return make_client(get_settings().redis_url)


def get_redis() -> redis.Redis:
    """FastAPI dependency; tests may point it at a dead port to check fail-open."""
    return _client()


def hit(client: redis.Redis, bucket: str, subject: str) -> None:
    """Count one request for `subject` in `bucket`; raise RateLimited past the limit."""
    global _skip_until
    if time.monotonic() < _skip_until:
        return
    settings = get_settings()
    limit = Limit.parse(settings.rate_limits[bucket])
    now = time.time()
    window = int(now // limit.seconds)
    key = f"{settings.rate_limit_prefix}:{bucket}:{subject}:{window}"
    try:
        pipe = client.pipeline(transaction=False)
        pipe.incr(key)
        pipe.expire(key, limit.seconds, nx=True)
        count = pipe.execute()[0]
    except redis.RedisError as exc:
        _skip_until = time.monotonic() + COOLDOWN_SECONDS
        logger.warning(
            "rate limiter unavailable (%s); allowing requests for %.0f s",
            type(exc).__name__,
            COOLDOWN_SECONDS,
        )
        return
    if count > limit.requests:
        retry_after = max(1, int((window + 1) * limit.seconds - now))
        raise RateLimited(headers={"Retry-After": str(retry_after)})


def subject_hash(value: str) -> str:
    """Keys hold a hash, not the raw value (e.g. an email address), so Redis has no PII."""
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def per_user(bucket: str) -> Callable[..., None]:
    """Route dependency: limit by signed-in user. Use after the permission dependency."""
    from app.api.deps import CurrentUser  # local import: api.deps imports core modules

    def dependency(user: CurrentUser, client: redis.Redis = Depends(get_redis)) -> None:  # noqa: B008
        hit(client, bucket, str(user.id))

    return dependency


def client_ip(request: Request) -> str:
    """The direct peer address. Behind a reverse proxy this would need the trusted
    X-Forwarded-For hop instead; this app runs without one."""
    return request.client.host if request.client else "unknown"

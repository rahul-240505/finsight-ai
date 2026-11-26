"""Engine and per-request database session."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """One connection pool per process. pool_pre_ping drops dead connections after a DB restart."""
    url = get_settings().database_url.get_secret_value()
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    # expire_on_commit=False: objects stay readable after commit (we return them as responses).
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed. Services commit explicitly;
    anything not committed is rolled back when the session closes."""
    with get_sessionmaker()() as session:
        yield session

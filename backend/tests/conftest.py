from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient around a fresh app per test, so overrides never leak between tests."""
    with TestClient(create_app()) as c:
        yield c

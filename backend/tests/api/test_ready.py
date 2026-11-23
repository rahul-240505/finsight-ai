import pytest
from fastapi.testclient import TestClient

from app.api.health import get_readiness_checks
from app.core.readiness import Check


def ok() -> None:
    return None


def broken() -> None:
    raise ConnectionError("db.internal:5432 password=hunter2 refused")


def use_checks(client: TestClient, checks: dict[str, Check]) -> None:
    client.app.dependency_overrides[get_readiness_checks] = lambda: checks  # type: ignore[attr-defined]


def test_ready_when_all_dependencies_up(client: TestClient) -> None:
    use_checks(client, {"postgres": ok, "redis": ok, "qdrant": ok})
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"postgres": "ok", "redis": "ok", "qdrant": "ok"},
    }


def test_not_ready_when_one_dependency_down(client: TestClient) -> None:
    use_checks(client, {"postgres": broken, "redis": ok, "qdrant": ok})
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["postgres"] == "down"
    assert response.json()["checks"]["redis"] == "ok"


def test_failure_details_never_reach_the_client(client: TestClient) -> None:
    use_checks(client, {"postgres": broken})
    body = client.get("/ready").text
    assert "hunter2" not in body
    assert "db.internal" not in body


@pytest.mark.integration
def test_ready_against_real_docker_stores(client: TestClient) -> None:
    """Needs `docker compose up` (locally) or CI service containers."""
    response = client.get("/ready")
    assert response.json() == {
        "status": "ready",
        "checks": {"postgres": "ok", "redis": "ok", "qdrant": "ok"},
    }
    assert response.status_code == 200

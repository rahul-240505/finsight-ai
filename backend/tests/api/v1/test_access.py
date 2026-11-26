"""Authorization: every route needs a login, roles limit actions, owners limit objects (IDOR)."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.permissions import Role
from app.main import create_app
from tests.conftest import BASE_URL, login

pytestmark = pytest.mark.integration

PUBLIC_ROUTES = {("POST", "/api/v1/auth/register"), ("POST", "/api/v1/auth/login")}
SAMPLE_ID = "00000000-0000-0000-0000-000000000000"


def api_routes() -> list[tuple[str, str]]:
    """Every /api/v1 route, read from the OpenAPI schema, so a new route can't silently skip
    authentication. (FastAPI 0.165 keeps included routers nested, so app.routes is not flat.)"""
    paths = create_app().openapi()["paths"]
    routes = [(m.upper(), p) for p, ops in paths.items() if p.startswith("/api/v1") for m in ops]
    return sorted(routes)


PRIVATE_ROUTES = [r for r in api_routes() if r not in PUBLIC_ROUTES]


def test_route_inventory_is_not_empty() -> None:
    """Guards the parametrized test below: an empty list would make it silently skip."""
    assert PUBLIC_ROUTES <= set(api_routes())
    assert len(PRIVATE_ROUTES) >= 7


@pytest.mark.parametrize(("method", "path"), PRIVATE_ROUTES)
def test_every_private_route_needs_login(api: TestClient, method: str, path: str) -> None:
    url = path.replace("{dataset_id}", SAMPLE_ID).replace("{user_id}", SAMPLE_ID)
    response = api.request(method, url, json={})
    assert response.status_code == 401, f"{method} {path} -> {response.status_code}"


def test_viewer_can_read_but_not_write(api: TestClient, make_user: Callable) -> None:
    login(api, make_user(Role.VIEWER))
    assert api.get("/api/v1/datasets").status_code == 200
    assert api.post("/api/v1/datasets", json={"name": "x"}).status_code == 403


def test_only_admin_can_change_roles_and_change_ends_sessions(
    api: TestClient, make_user: Callable
) -> None:
    target = make_user()
    with TestClient(api.app, base_url=BASE_URL) as target_client:
        login(target_client, target)
        url = f"/api/v1/users/{target.id}/role"

        login(api, make_user(Role.ANALYST))
        assert api.patch(url, json={"role": "admin"}).status_code == 403

        login(api, make_user(Role.ADMIN))
        response = api.patch(url, json={"role": "viewer"})
        assert response.status_code == 200 and response.json()["role"] == "viewer"
        assert target_client.get("/api/v1/auth/me").status_code == 401  # old session ended


def test_user_cannot_see_or_delete_another_users_dataset(
    api: TestClient, make_user: Callable
) -> None:
    owner, other = make_user(), make_user()
    login(api, owner)
    dataset_id = api.post("/api/v1/datasets", json={"name": "Q3 cards"}).json()["id"]

    login(api, other)
    assert api.get(f"/api/v1/datasets/{dataset_id}").status_code == 404
    assert api.delete(f"/api/v1/datasets/{dataset_id}").status_code == 404
    assert api.get("/api/v1/datasets").json() == []

    login(api, owner)
    assert api.get(f"/api/v1/datasets/{dataset_id}").status_code == 200  # still there


def test_foreign_and_missing_ids_give_the_same_response(
    api: TestClient, make_user: Callable
) -> None:
    owner, other = make_user(), make_user()
    login(api, owner)
    dataset_id = api.post("/api/v1/datasets", json={"name": "mine"}).json()["id"]
    login(api, other)
    foreign = api.get(f"/api/v1/datasets/{dataset_id}")
    missing = api.get(f"/api/v1/datasets/{SAMPLE_ID}")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["code"] == missing.json()["error"]["code"]


def test_list_is_paginated_and_capped(api: TestClient, make_user: Callable) -> None:
    login(api, make_user())
    for i in range(3):
        api.post("/api/v1/datasets", json={"name": f"d{i}"})
    first = api.get("/api/v1/datasets", params={"limit": 2}).json()
    second = api.get("/api/v1/datasets", params={"limit": 2, "offset": 2}).json()
    # Pages don't overlap and together cover everything. (All three rows share created_at here,
    # because Postgres now() is the transaction start time; the id tie-breaker keeps order stable.)
    assert len(first) == 2 and len(second) == 1
    assert {d["name"] for d in first + second} == {"d0", "d1", "d2"}
    assert first == api.get("/api/v1/datasets", params={"limit": 2}).json()
    assert api.get("/api/v1/datasets", params={"limit": 101}).status_code == 422

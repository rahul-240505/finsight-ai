"""Error shape, request IDs and the CSRF Origin check. No database needed."""

from fastapi.testclient import TestClient


def test_unknown_route_uses_error_shape_with_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["x-request-id"]


def test_incoming_request_id_is_kept_and_bad_ones_replaced(client: TestClient) -> None:
    assert (
        client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"]
        == "abc-123"
    )
    replaced = client.get("/health", headers={"X-Request-ID": "bad id\n"}).headers["x-request-id"]
    assert replaced != "bad id\n" and len(replaced) == 36


def test_validation_error_never_echoes_submitted_values(client: TestClient) -> None:
    secret = "hunter2-hunter2"
    response = client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": secret}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert secret not in response.text
    assert {f["field"] for f in response.json()["error"]["fields"]} == {"body.email"}


def test_cross_site_post_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={}, headers={"Origin": "https://evil.test"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_allowed_and_same_origin_posts_pass_the_csrf_check(client: TestClient) -> None:
    for origin in ("http://localhost:5173", "https://testserver"):
        response = client.post("/api/v1/auth/login", json={}, headers={"Origin": origin})
        assert response.status_code == 422  # reached the route; failed validation instead

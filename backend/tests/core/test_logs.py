import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.logs import ContextFilter, JsonFormatter, job_id_var, request_id_var
from tests.conftest import PASSWORD, import_csv, login, make_csv


def render(record: logging.LogRecord) -> dict:
    ContextFilter().filter(record)
    return json.loads(JsonFormatter().format(record))


def test_json_line_has_context_and_extras() -> None:
    token = job_id_var.set("job-1")
    try:
        record = logging.makeLogRecord(
            {
                "name": "x",
                "levelname": "INFO",
                "msg": "hi %s",
                "args": ("there",),
                "duration_ms": 1.5,
            }
        )
        entry = render(record)
    finally:
        job_id_var.reset(token)
    assert entry["msg"] == "hi there"
    assert entry["job_id"] == "job-1"
    assert entry["duration_ms"] == 1.5
    assert "request_id" not in entry  # empty context values are left out


def test_exception_is_logged_with_type() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", None, True)
        record.exc_info = __import__("sys").exc_info()
    entry = render(record)
    assert entry["exc_type"] == "ValueError"
    assert "Traceback" in entry["exc"]


def access_lines(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [render(r) for r in caplog.records if r.name == "app.access"]


def test_access_log_per_request(api: TestClient, make_user, caplog) -> None:
    user = make_user()
    login(api, user)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        response = api.get("/api/v1/datasets/00000000-0000-0000-0000-000000000000")
    (line,) = access_lines(caplog)
    assert line["request_id"] == response.headers["x-request-id"]
    assert line["path"] == "/api/v1/datasets/{dataset_id}"  # template, not the raw id
    assert line["status"] == 404
    assert line["user_id"] == str(user.id)
    assert line["duration_ms"] >= 0


def test_logs_never_contain_the_password_or_cookie(api: TestClient, make_user, caplog) -> None:
    user = make_user()
    with caplog.at_level(logging.DEBUG):
        login(api, user)
        api.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong-" + PASSWORD})
    cookie = api.cookies.get("finsight_session")
    text = "\n".join(JsonFormatter().format(r) for r in caplog.records)
    assert PASSWORD not in text and cookie and cookie not in text


def test_job_logs_carry_the_job_id(api: TestClient, make_user, caplog) -> None:
    login(api, make_user())
    with caplog.at_level(logging.INFO):
        import_csv(api, make_csv(3))
    job_lines = [render(r) for r in caplog.records if r.name == "app.modules.jobs.runner"]
    assert job_lines and all(line.get("job_id") for line in job_lines)
    assert job_id_var.get() is None and request_id_var.get() is None  # context cleaned up

"""HTTP middleware: request IDs, the access log and the CSRF Origin check."""

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import error_body
from app.core.logs import request_id_var

access_log = logging.getLogger("app.access")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")

Next = Callable[[Request], Awaitable[Response]]


def install_middleware(app: FastAPI) -> None:
    # Registered first = runs innermost. csrf runs inside request_id, so its 403 has an ID.
    @app.middleware("http")
    async def csrf_origin_check(request: Request, call_next: Next) -> Response:
        """Reject state-changing requests that a browser sent from a foreign site.

        SameSite=Lax cookies already stop most cross-site requests; this is the second layer.
        Requests without an Origin header (curl, server-to-server, tests) carry no browser
        cookie risk and are allowed.
        """
        origin = request.headers.get("origin")
        if request.method in UNSAFE_METHODS and origin is not None:
            same_origin = origin == f"{request.url.scheme}://{request.url.netloc}"
            if not same_origin and origin not in get_settings().allowed_origins:
                body = error_body(request, "csrf_failed", "Request origin not allowed.")
                return JSONResponse(body, 403)
        return await call_next(request)

    @app.middleware("http")
    async def request_id(request: Request, call_next: Next) -> Response:
        """Accept a sane incoming X-Request-ID (so traces can span services) or make one."""
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _VALID_REQUEST_ID.match(incoming) else str(uuid.uuid4())
        request.state.request_id = rid
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            _log_access(request, status, started)
            request_id_var.reset(token)


def _log_access(request: Request, status: int, started: float) -> None:
    """One line per request. The path is the route template (`/reports/{report_id}`), never
    the query string, so ids and file names typed by users stay out of the log."""
    access_log.info(
        "request",
        extra={
            "method": request.method,
            "path": _route_template(request),
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "user_id": str(getattr(request.state, "user_id", "") or "") or None,
        },
    )


def _route_template(request: Request) -> str:
    """Nested routers store only their own part of the path (`/datasets/{dataset_id}`); the
    prefix is the matching number of leading segments of the real URL path."""
    route_path = getattr(request.scope.get("route"), "path", None)
    if not route_path:
        return "unmatched"
    parts = request.url.path.split("/")
    return "/".join(parts[: len(parts) - route_path.count("/")]) + route_path

"""HTTP middleware: request IDs and the CSRF Origin check."""

import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import error_body

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
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

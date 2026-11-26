"""One JSON error shape for every failure: {"error": {"code", "message", "request_id"}}.

Services raise AppError subclasses; they never build HTTP responses themselves.
Stack traces and raw input values never reach the client.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    message = "Bad request."

    def __init__(self, message: str | None = None, **extra: object) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.extra = extra  # extra JSON fields for the error body (e.g. per-row errors)


class Unauthorized(AppError):
    status_code, code, message = 401, "unauthorized", "Not signed in."


class Forbidden(AppError):
    status_code, code, message = 403, "forbidden", "Not allowed."


class NotFound(AppError):
    """Also used for objects owned by someone else, so their existence is never revealed."""

    status_code, code, message = 404, "not_found", "Not found."


class Conflict(AppError):
    status_code, code, message = 409, "conflict", "Conflict."


class BadRequest(AppError):
    status_code, code, message = 400, "bad_request", "Bad request."


class PayloadTooLarge(AppError):
    status_code, code, message = 413, "payload_too_large", "The upload is too large."


class UnsupportedMediaType(AppError):
    status_code, code, message = 415, "unsupported_media_type", "Unsupported content type."


def error_body(request: Request, code: str, message: str, **extra: object) -> dict:
    request_id = getattr(request.state, "request_id", None)
    return {"error": {"code": code, "message": message, "request_id": request_id, **extra}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        body = error_body(request, exc.code, exc.message, **exc.extra)
        return JSONResponse(body, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and reasons only. FastAPI's default also echoes the submitted
        # value ("input"), which would put passwords into responses and logs.
        fields = [
            {"field": ".".join(str(p) for p in err["loc"]), "reason": err["msg"]}
            for err in exc.errors()
        ]
        body = error_body(request, "validation_error", "Invalid request.", fields=fields)
        return JSONResponse(body, 422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed"}
        code = codes.get(exc.status_code, "http_error")
        return JSONResponse(error_body(request, code, str(exc.detail)), exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        rid = getattr(request.state, "request_id", None)
        logger.exception("unhandled error (request_id=%s)", rid)
        return JSONResponse(error_body(request, "internal_error", "Something went wrong."), 500)

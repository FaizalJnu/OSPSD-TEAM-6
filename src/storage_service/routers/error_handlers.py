"""How errors appear over HTTP, in the OpenAPI schema, and in the failure log.

The service raises plain Python errors (see ``errors.py``). This module is the
only place that turns them into status codes and JSON bodies. It also gives our
format to the errors FastAPI and Starlette raise before or around our code: a path
with no route, a method the path does not accept, a body that cannot be read, and a
bug. ``main.create_app`` registers the handlers.

Every failed request also writes one JSON line to the log. It says which operation
failed, with which error and status, whether the provider was involved, and for a
write whether it was attempted. It never contains the provider's own message, which
can name the account and bucket, and expected failures get no traceback.
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from cloud_storage_api import errors as shared
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.routing import Match

from storage_service.errors import (
    InvalidInput,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ErrorDetail:
    """The JSON body of every error response.

    The stable code identifies the failure; message is a safe explanation for people.
    """

    code: str
    message: str


@dataclass(frozen=True)
class ErrorBody:
    """Common JSON envelope; programs branch on error.code."""

    error: ErrorDetail


# What the caller sees when the service has a bug, whatever went wrong.
_INTERNAL_ERROR = ErrorDetail("internal_error", "the service failed unexpectedly")

# How each of our errors appears over HTTP. Anything not listed is a bug: a 500.
_STATUS_FOR_ERROR: dict[type[shared.StorageError], int] = {
    shared.InvalidRequestError: 400,
    shared.PermissionDeniedError: 403,
    shared.NotFoundError: 404,
    shared.ConflictError: 409,
    shared.FileTooLargeError: 413,
    shared.ProviderError: 502,
    shared.ProviderUnavailableError: 503,
    shared.InvalidOperationError: 422,
}

# Route names (the endpoint functions) of the operations that change stored files,
# and the storage calls that do the change.
_WRITE_OPERATIONS = {"create_file", "replace_file", "delete_file"}
_WRITE_CALLS = {"put", "delete", "delete_many"}

# The methods a route can accept, in the order a 405's Allow header lists them.
_HTTP_METHODS = ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT")


def storage_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Turn a StorageError raised anywhere below the routes into a JSON error response."""
    assert isinstance(exc, shared.StorageError)
    status = next(
        (code for error_type, code in _STATUS_FOR_ERROR.items() if isinstance(exc, error_type)),
        None,
    )
    if status is None:
        return internal_error_handler(request, exc)
    return _storage_error_response(request, exc, status)


def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI rejected the input before our code ran. Report it like any other bad input."""
    assert isinstance(exc, RequestValidationError)
    problem = exc.errors()[0]  # e.g. {"loc": ("query", "limit"), "msg": "Input should be ..."}
    # "limit", "file", ...; for a body that is not JSON, loc ends in a character position.
    field = "body" if problem["type"] == "json_invalid" else problem["loc"][-1]
    return _storage_error_response(request, InvalidInput(f"{field}: {problem['msg']}"), 400)


def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Give the errors Starlette raises itself our format.

    * 400: the request body cannot be read, for example a multipart body without a
      boundary. The only body this service reads is the ``file`` form field of Create
      and Replace, so this is ``InvalidInput`` for ``file``.
    * 404: the path matches no route. ``RouteNotFound`` keeps a wrong URL apart from
      a missing file (``FileNotFound``).
    * 405: the path exists, but not for this method.

    Nothing else raises an HTTPException here, so any other status is a bug.
    """
    assert isinstance(exc, HTTPException)
    if exc.status_code == 400:
        return _storage_error_response(request, InvalidInput(f"file: {exc.detail}"), 400)
    if exc.status_code == 404:
        body = ErrorDetail("route_not_found", "no route matches this path")
    elif exc.status_code == 405:
        body = ErrorDetail("method_not_allowed", f"this path does not accept {request.method}")
    else:
        return internal_error_handler(request, exc)
    # No operation ran. For a 405, Starlette matched the path to a route of another
    # method, but did not run it.
    _log_failure(exc.status_code, body, operation=None, provider_involved=False)
    headers = dict(exc.headers or {})
    if exc.status_code == 405:
        headers["Allow"] = _allowed_methods(request)
    return _error_response(exc.status_code, body, headers)


def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """A bug: return a 500 that reveals nothing, and log it with its traceback.

    We cannot tell where the bug struck, so the log does not say whether the provider
    was involved, and on a write it says the write may have happened. When Starlette
    calls this for an exception nothing else handled, it re-raises the exception
    afterwards, so the server prints it as well.
    """
    _log_failure(
        500, _INTERNAL_ERROR, operation=_operation(request), provider_involved=None, exc_info=exc
    )
    return _error_response(500, _INTERNAL_ERROR)


def log_interrupted_download(
    request: Request, exc: Exception, *, bytes_sent: int, size: int
) -> None:
    """Log a download that failed after its 200 status and headers were sent.

    The caller cannot be sent an error any more: it sees a body shorter than
    ``Content-Length`` instead. So the line says ``"status": 200``, names the error the
    caller could not be told about, and adds ``"interrupted": true``, the bytes sent,
    and the file's size. A ``StorageError`` here came from reading the chunks of the
    storage call ``get``. Anything else is a bug, logged with its traceback.
    """
    extra = {"interrupted": True, "bytes_sent": bytes_sent, "size": size}
    if isinstance(exc, shared.StorageError):
        _log_failure(
            200,
            ErrorDetail(exc.code, str(exc)),
            operation=_operation(request),
            provider_involved=True,
            storage_call="get",
            provider_code=getattr(exc, "provider_code", None),
            extra=extra,
        )
    else:
        _log_failure(
            200,
            _INTERNAL_ERROR,
            operation=_operation(request),
            provider_involved=None,
            exc_info=exc,
            extra=extra,
        )


def error_responses(descriptions: Mapping[int, str]) -> dict[int | str, dict[str, Any]]:
    """A route's error responses for the OpenAPI schema, each with our error body.

    Pass ``{status: "<error code>: <when>"}``. 500 ``internal_error`` is added, since
    a bug can make any route fail.
    """
    every = {**descriptions, 500: "internal_error: the service failed unexpectedly."}
    return {status: {"model": ErrorBody, "description": text} for status, text in every.items()}


def remove_validation_responses(app: FastAPI) -> None:
    """Remove the 422 that FastAPI adds to every route with parameters from the schema.

    ``validation_error_handler`` turns those failures into 400 ``invalid_request``, which
    each route lists through ``error_responses``. Replacing ``app.openapi`` is how
    FastAPI's docs say to change the generated schema.
    """
    build_schema = app.openapi

    def openapi() -> dict[str, Any]:
        schema = build_schema()  # built once, then cached by FastAPI
        for operations in schema["paths"].values():
            for operation in operations.values():
                if "422" in operation["responses"]:
                    response = operation["responses"]["422"]
                    model = (
                        response.get("content", {}).get("application/json", {}).get("schema", {})
                    )
                    if model.get("$ref", "").endswith("/HTTPValidationError"):
                        operation["responses"].pop("422")
        schemas = schema.get("components", {}).get("schemas", {})
        for name in ("HTTPValidationError", "ValidationError"):
            schemas.pop(name, None)
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


def _storage_error_response(
    request: Request, error: shared.StorageError, status: int
) -> JSONResponse:
    body = ErrorDetail(error.code, str(error))
    _log_failure(
        status,
        body,
        operation=_operation(request),
        provider_involved=getattr(error, "storage_call", None) is not None,
        storage_call=getattr(error, "storage_call", None),
        provider_code=getattr(error, "provider_code", None),
    )
    return _error_response(status, body)


def _error_response(
    status: int, body: ErrorDetail, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=status, content=asdict(ErrorBody(body)), headers=headers)


def _operation(request: Request) -> str | None:
    """The operation the request ran: its route's endpoint name, such as ``create_file``."""
    return getattr(request.scope.get("route"), "name", None)


def _allowed_methods(request: Request) -> str:
    """Every method some route accepts for this path, for a 405's ``Allow`` header.

    Starlette's own header names only the first route that matches the path: ``POST``
    for ``/files/{key}``, which also accepts PUT. So ask every route
    whether it would accept the path with each method.
    """
    path = {
        "type": "http",
        "path": request.scope["path"],
        "root_path": request.scope.get("root_path", ""),
    }
    return ", ".join(
        method
        for method in _HTTP_METHODS
        if any(
            route.matches({**path, "method": method})[0] is Match.FULL
            for route in request.app.routes
        )
    )


def _log_failure(
    status: int,
    body: ErrorDetail,
    *,
    operation: str | None,
    provider_involved: bool | None,
    storage_call: str | None = None,
    provider_code: str | None = None,
    exc_info: BaseException | None = None,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Write one JSON line describing a failed request.

    ``status`` is what the caller received, and ``body`` the error it was sent (or, for
    an interrupted download, could not be sent). ``extra`` adds fields at the end.
    ``operation`` is ``None`` when
    the request matched no operation, and ``provider_involved`` is ``None`` when we
    cannot know (a bug). ``write_outcome`` (Create, Replace, and Delete only) is
    ``not_attempted`` when the request failed before the write call, and ``unknown``
    when the write call itself failed, or a bug may have struck after it: the provider
    may have completed it (see "After a failed write" in docs/API.md). Only a bug is
    logged with its traceback.
    """
    # The caller can fix a 4xx, except a denial of the service's own credentials.
    # Anything else (a 5xx, or a 200 whose body was cut off) needs whoever runs the
    # service.
    caller_can_fix = 400 <= status < 500 and body.code != "permission_denied"
    level = logging.WARNING if caller_can_fix else logging.ERROR
    event: dict[str, object] = {
        "level": logging.getLevelName(level),
        "event": "request_failed",
        "operation": operation,
        "status": status,
        "error": body.code,
        "detail": body.message,
        "provider_involved": provider_involved,
        "storage_call": storage_call,
    }
    if provider_code is not None:
        event["provider_code"] = provider_code
    if operation in _WRITE_OPERATIONS:
        may_have_written = provider_involved is None or storage_call in _WRITE_CALLS
        event["write_outcome"] = "unknown" if may_have_written else "not_attempted"
    if extra is not None:
        event.update(extra)
    logger.log(level, json.dumps(event), exc_info=exc_info)

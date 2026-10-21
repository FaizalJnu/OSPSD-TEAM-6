"""How our errors appear over HTTP, and in the failure log.

The service raises plain Python errors (see ``errors.py``). This module is the
only place that turns them into status codes and JSON bodies. ``main.create_app``
registers the handlers.

Every failed request also writes one JSON line to the log. It says which operation
failed, with which error and status, whether the provider was involved, and for a
write whether it was attempted. It never contains the provider's own message, which
can name the account and bucket, and expected failures get no traceback.
"""

import json
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from storage_service.errors import (
    AccessDenied,
    FileAlreadyExists,
    FileNotFound,
    FileTooLarge,
    InvalidInput,
    ProviderError,
    ProviderUnavailable,
    StorageError,
)

logger = logging.getLogger(__name__)


# How each of our errors appears over HTTP. Anything not listed becomes a 500.
_STATUS_FOR_ERROR: dict[type[StorageError], int] = {
    InvalidInput: 400,
    AccessDenied: 403,
    FileNotFound: 404,
    FileAlreadyExists: 409,
    FileTooLarge: 413,
    ProviderError: 502,
    ProviderUnavailable: 503,
}

# Route names (the endpoint functions) of the operations that change stored files,
# and the storage calls that do the change.
_WRITE_OPERATIONS = {"create_file", "replace_file", "delete_file"}
_WRITE_CALLS = {"put", "delete"}


def storage_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Turn a StorageError raised anywhere below the routes into a JSON error response."""
    assert isinstance(exc, StorageError)
    status = next(
        (code for error_type, code in _STATUS_FOR_ERROR.items() if isinstance(exc, error_type)),
        500,
    )
    _log_failure(request, exc, status)
    return JSONResponse(
        status_code=status, content={"error": type(exc).__name__, "detail": str(exc)}
    )


def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI rejected the input before our code ran. Report it like any other bad input."""
    assert isinstance(exc, RequestValidationError)
    problem = exc.errors()[0]  # e.g. {"loc": ("query", "limit"), "msg": "Input should be ..."}
    field = problem["loc"][-1]  # "limit", "file", ...
    error = InvalidInput(f"{field}: {problem['msg']}")
    status = _STATUS_FOR_ERROR[InvalidInput]
    _log_failure(request, error, status)
    return JSONResponse(
        status_code=status, content={"error": type(error).__name__, "detail": str(error)}
    )


def _log_failure(request: Request, error: StorageError, status: int) -> None:
    """Write one JSON line describing a failed request.

    ``write_outcome`` (Create, Replace, and Delete only) is ``not_attempted`` when the
    request failed before the write call, and ``unknown`` when the write call itself
    failed: the provider may have completed it (see "After a failed write" in
    docs/API.md). Only an unexpected 500 is logged with its traceback.
    """
    route = request.scope.get("route")
    operation = getattr(route, "name", None) or "unknown"
    # The caller can fix a 4xx. A 5xx, or a denial of the service's own credentials,
    # needs whoever runs the service.
    needs_operator = status >= 500 or isinstance(error, AccessDenied)
    level = logging.ERROR if needs_operator else logging.WARNING
    event: dict[str, object] = {
        "level": logging.getLevelName(level),
        "event": "request_failed",
        "operation": operation,
        "status": status,
        "error": type(error).__name__,
        "detail": str(error),
        "provider_involved": error.storage_call is not None,
        "storage_call": error.storage_call,
    }
    if error.provider_code is not None:
        event["provider_code"] = error.provider_code
    if operation in _WRITE_OPERATIONS:
        attempted = error.storage_call in _WRITE_CALLS
        event["write_outcome"] = "unknown" if attempted else "not_attempted"
    logger.log(level, json.dumps(event), exc_info=error if status == 500 else None)

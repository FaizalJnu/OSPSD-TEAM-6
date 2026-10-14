"""How our errors appear over HTTP.

The service raises plain Python errors (see ``errors.py``). This module is the
only place that turns them into status codes and JSON bodies. ``main.create_app``
registers the handlers.
"""

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from storage_service.errors import (
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
    FileNotFound: 404,
    FileAlreadyExists: 409,
    FileTooLarge: 413,
    ProviderError: 502,
    ProviderUnavailable: 503,
}


def storage_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Turn a StorageError raised anywhere below the routes into a JSON error response."""
    status = next(
        (code for error_type, code in _STATUS_FOR_ERROR.items() if isinstance(exc, error_type)),
        500,
    )
    if status >= 500:
        # Server-side problems get logged with the full chain of causes for whoever
        # runs the service. The client only sees our short, safe message.
        logger.error("%s %s failed", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=status, content={"error": type(exc).__name__, "detail": str(exc)}
    )


def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI rejected the input before our code ran. Report it like any other bad input."""
    assert isinstance(exc, RequestValidationError)
    problem = exc.errors()[0]  # e.g. {"loc": ("query", "limit"), "msg": "Input should be ..."}
    field = problem["loc"][-1]  # "limit", "file", ...
    return JSONResponse(
        status_code=_STATUS_FOR_ERROR[InvalidInput],
        content={"error": InvalidInput.__name__, "detail": f"{field}: {problem['msg']}"},
    )

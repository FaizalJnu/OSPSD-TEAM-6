"""Serve the Milestone 1 workflow using its single, dedicated test account."""

import hmac
import json
import logging
import os
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from meeting_prep.adapters.calendar import EventCalendarAdapter
from meeting_prep.adapters.storage import DocumentStorageAdapter
from meeting_prep.adapters.tracker import IssueTrackerAdapter
from meeting_prep.config import load_settings, require
from meeting_prep.factories import build_implementations
from meeting_prep.orchestrator import (
    AGENDA_ITEM_LENGTH,
    AGENDA_ITEMS,
    TITLE_LENGTH,
    Orchestrator,
    ReviewMeetingError,
)

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 64 * 1024
_STATUS = {
    "invalid_request": 400,
    "unauthorized": 401,
    "permission_denied": 403,
    "run_in_progress": 409,
    "outcome_unknown": 409,
    "run_record_invalid": 409,
    "provider_error": 502,
    "provider_unavailable": 503,
    "internal_error": 500,
}


def create_app() -> FastAPI:
    """ASGI factory, intended for the fixed workflow with a dedicated test account."""
    key = require(os.environ, "PRODUCT_API_KEY")
    implementations = build_implementations(load_settings())
    storage = DocumentStorageAdapter(implementations.storage)
    tracker = IssueTrackerAdapter(implementations.tracker)
    calendar = EventCalendarAdapter(implementations.calendar)
    return build_app(
        Orchestrator(storage, tracker, calendar),
        api_key=key,
        commit=os.environ.get("RELEASE", "unknown"),
        storage_health=storage.check_health,
        tracker_health=lambda: tracker.list_issues(1),
    )


def build_app(
    workflow: Orchestrator,
    *,
    api_key: str,
    commit: str,
    storage_health: Callable[[], object],
    tracker_health: Callable[[], object],
) -> FastAPI:
    if not api_key.strip():
        raise ValueError("PRODUCT_API_KEY must be set")
    app = FastAPI(title="Meeting Prep")
    expected = api_key.encode()

    def authorized(
        token: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(HTTPBearer(auto_error=False, scheme_name="ProductBearer")),
        ],
    ) -> bool:
        return token is not None and hmac.compare_digest(token.credentials.encode(), expected)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "commit": commit}

    @app.get("/health/providers")
    def readiness(has_key: Annotated[bool, Depends(authorized)]) -> JSONResponse:
        if not has_key:
            return _unauthorized()
        checks = {"storage": _probe(storage_health), "tracker": _probe(tracker_health)}
        ready = all(status == "ok" for status in checks.values())
        return JSONResponse(
            {
                "status": "ok" if ready else "unavailable",
                "providers": {**checks, "calendar": "unchecked"},
            },
            status_code=200 if ready else 503,
        )

    @app.post(
        "/v1/review-meetings",
        status_code=201,
        responses={
            200: {"description": "Completed run replay"},
            400: {"description": "Invalid request"},
            401: {"description": "Missing or invalid bearer key"},
            403: {"description": "Provider denied access"},
            409: {"description": "Run in progress, invalid run record, or unknown outcome"},
            500: {"description": "Internal error"},
            502: {"description": "Provider error"},
            503: {"description": "Provider unavailable"},
        },
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["title", "start", "end", "agenda"],
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": f"1 to {TITLE_LENGTH} characters after trimming",
                                },
                                "start": {"type": "string", "format": "date-time"},
                                "end": {"type": "string", "format": "date-time"},
                                "agenda": {
                                    "type": "array",
                                    "maxItems": AGENDA_ITEMS,
                                    "items": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": AGENDA_ITEM_LENGTH,
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    )
    async def review_meeting(
        request: Request, has_key: Annotated[bool, Depends(authorized)]
    ) -> JSONResponse:
        if not has_key:
            return _unauthorized()
        try:
            body = await _body(request)
            result = await run_in_threadpool(workflow.run, body)
        except ReviewMeetingError as error:
            return _fail(error)
        except Exception as error:
            # A provider SDK exception or validation failure can contain request data.
            return _fail(
                ReviewMeetingError("internal_error", "The service failed unexpectedly."),
                exception_type=type(error).__name__,
            )
        return JSONResponse(result.body(), status_code=200 if result.replayed else 201)

    @app.exception_handler(HTTPException)
    async def framework_error(_request: Request, error: HTTPException) -> JSONResponse:
        if error.status_code == 404:
            code, message = "route_not_found", "No route matches this path."
        elif error.status_code == 405:
            code, message = "method_not_allowed", "This route does not accept that method."
        else:
            code, message = "internal_error", "The service failed unexpectedly."
        return JSONResponse(
            {"error": {"code": code, "message": message}},
            status_code=error.status_code if error.status_code in {404, 405} else 500,
            headers=error.headers if error.status_code == 405 else None,
        )

    return app


def _unauthorized() -> JSONResponse:
    return _fail(ReviewMeetingError("unauthorized", "A valid API key is required."))


async def _body(request: Request) -> dict[str, object]:
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_REQUEST_BYTES:
            raise ReviewMeetingError("invalid_request", "The request body is too large.")
        data.extend(chunk)
    try:
        body = json.loads(data)
    except ValueError, RecursionError:
        raise ReviewMeetingError("invalid_request", "Send a JSON object.") from None
    if not isinstance(body, dict):
        raise ReviewMeetingError("invalid_request", "Send a JSON object.")
    return body


def _probe(check: Callable[[], object]) -> str:
    try:
        check()
    except Exception:
        return "unavailable"
    return "ok"


def _fail(error: ReviewMeetingError, *, exception_type: str | None = None) -> JSONResponse:
    log_failure(error, exception_type=exception_type)
    headers = {}
    if error.retry_after is not None:
        headers["Retry-After"] = str(error.retry_after)
    if error.code == "unauthorized":
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(error.body(), status_code=_STATUS[error.code], headers=headers)


def log_failure(error: ReviewMeetingError, *, exception_type: str | None = None) -> None:
    run = error.run or {}
    logger.warning(
        "%s",
        json.dumps(
            {
                "event": "review_meeting_failed",
                "run_id": run.get("run_id"),
                "step": error.step,
                "code": error.code,
                "provider_code": error.provider_code,
                "provider_cause": error.provider_cause,
                "may_have_applied": error.may_have_applied,
                "steps": run.get("steps"),
                "exception_type": exception_type,
            }
        ),
    )

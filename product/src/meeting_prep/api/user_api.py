"""Authenticated API for the agent's reads and approved writes."""

import os
from collections.abc import Callable
from dataclasses import asdict
from datetime import timedelta
from typing import Annotated, TypedDict

from fastapi import Depends, FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from meeting_prep.adapters.base import IssueSummary, StepError
from meeting_prep.adapters.calendar import EventSummary
from meeting_prep.adapters.storage import DocumentReadError
from meeting_prep.agent.api_client import ActionOutcome, Document, OutcomeStatus
from meeting_prep.agent.app import BodyLimit
from meeting_prep.agent.proposals import REVIEW_MEETING, approval_matches
from meeting_prep.api.main import log_failure
from meeting_prep.api.providers import UserProviders, build_user_providers, user_providers_mode
from meeting_prep.api.sign_in import (
    AuthError,
    GoogleIdentity,
    IdentityProvider,
    Principal,
    SessionAuth,
)
from meeting_prep.config import require
from meeting_prep.db import create_engine_for
from meeting_prep.db.agent_store import AgentStore
from meeting_prep.db.connection_store import ConnectionStore
from meeting_prep.db.identity_store import IdentityStore
from meeting_prep.orchestrator import InProcessRunLocks, Orchestrator, ReviewMeetingError
from meeting_prep.token_cipher import TokenCipher


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class OpenIssues(TypedDict):
    issues: list[IssueSummary]


class UpcomingEvents(TypedDict):
    events: list[EventSummary]


class Outcomes(TypedDict):
    outcomes: list[ActionOutcome]


PROVIDER_STATUS = {"permission_denied": 403, "provider_unavailable": 503, "provider_error": 502}
DOCUMENT_STATUS = {
    "invalid_request": 400,
    "not_found": 404,
    "document_too_large": 413,
    "unsupported_document": 415,
}


def create_user_app() -> FastAPI:
    engine = create_engine_for(require(os.environ, "DATABASE_URL"))
    auth = SessionAuth(IdentityStore(engine), require(os.environ, "PUBLIC_ORIGIN"))
    google = GoogleIdentity(
        require(os.environ, "GOOGLE_SIGNIN_CLIENT_ID"),
        require(os.environ, "GOOGLE_SIGNIN_CLIENT_SECRET"),
        auth.origin + "/v1/auth/callback",
    )
    connections = (
        ConnectionStore(engine, TokenCipher.from_env(os.environ))
        if user_providers_mode(os.environ) == "connections"
        else None
    )
    return build_user_app(
        auth,
        google,
        AgentStore(engine),
        build_user_providers(os.environ, connections),
        release=os.environ.get("RELEASE", "unknown"),
    )


def build_user_app(
    auth: SessionAuth,
    identity: IdentityProvider,
    proposals: AgentStore,
    providers_for: Callable[[str], UserProviders],
    *,
    release: str = "unknown",
) -> FastAPI:
    app = FastAPI(title="Meeting prep user API")
    app.add_middleware(BodyLimit, limit=16 * 1024)
    app.include_router(auth.router(identity))
    proposal_locks = InProcessRunLocks()
    workflow_locks = InProcessRunLocks()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "commit": release}

    @app.get("/v1/issues/open", response_model=OpenIssues)
    def open_issues(
        principal: Annotated[Principal, Depends(auth.require)],
        limit: Annotated[int, Query(ge=1, le=25)] = 10,
    ) -> JSONResponse:
        tracker = providers_for(principal.user.id).tracker
        if tracker is None:
            return _error(503, "provider_unavailable", "Connect your issue tracker first.")
        return _reply({"issues": [asdict(issue) for issue in tracker.list_issues(limit)]})

    @app.get("/v1/calendar/upcoming", response_model=UpcomingEvents)
    def upcoming(
        principal: Annotated[Principal, Depends(auth.require)],
        days: Annotated[int, Query(ge=1, le=60)] = 14,
    ) -> JSONResponse:
        calendar = providers_for(principal.user.id).calendar
        if calendar is None:
            return _error(503, "provider_unavailable", "Connect your calendar first.")
        now = auth.clock()
        return _reply(
            {
                "events": [
                    asdict(event) for event in calendar.upcoming(now, now + timedelta(days=days))
                ]
            }
        )

    @app.get("/v1/documents", response_model=Document)
    def document(
        principal: Annotated[Principal, Depends(auth.require)],
        path: Annotated[str, Query(min_length=2, max_length=900)],
    ) -> JSONResponse:
        storage = providers_for(principal.user.id).storage
        if storage is None:
            return _error(503, "provider_unavailable", "Document storage is unavailable.")
        return _reply(
            {"path": path, "content": storage.for_user(principal.user.id).read_text(path)}
        )

    @app.post("/v1/proposals/{proposal_id}/execute", response_model=Outcomes)
    def execute(
        proposal_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
        body: ExecuteRequest,
        request: Request,
        principal: Annotated[Principal, Depends(auth.require)],
    ) -> JSONResponse:
        user_id = principal.user.id
        # This deployment uses one API worker. The workflow's saved run record
        # handles storage/provider interruptions across a restart.
        with proposal_locks.hold(proposal_id):
            auth.require(request)
            proposal = proposals.get_proposal(user_id, proposal_id)
            if proposal is None:
                return _error(404, "not_found", "No such proposal.")
            approval = proposals.approval_for(user_id, proposal_id)
            if (
                proposal.status not in {"approved", "executed"}
                or approval is None
                or approval.id != body.approval_id
                or body.proposal_hash != proposal.hash
                or not approval_matches(approval, proposal, user_id)
            ):
                return _error(409, "approval_required", "Approve the current proposal first.")
            if proposal.status == "executed":
                return _outcomes(proposals.outcomes(user_id, proposal_id))
            if len(proposal.actions) != 1 or proposal.actions[0].kind != REVIEW_MEETING:
                return _error(400, "invalid_request", "This proposal has an unsupported action.")

            owned = providers_for(user_id)
            if owned.storage is None or owned.tracker is None or owned.calendar is None:
                return _error(
                    503, "provider_unavailable", "The required providers are unavailable."
                )
            workflow = Orchestrator(
                owned.storage.for_user(user_id),
                owned.tracker,
                owned.calendar,
                clock=auth.clock,
                locks=workflow_locks,
                user_id=user_id,
            )
            outcome, failure = _run_action(workflow, dict(proposal.actions[0].arguments))
            if failure is not None and failure.retryable:
                status = 409 if failure.code == "run_in_progress" else 503
                return _error(
                    status,
                    failure.code,
                    failure.message,
                    may_have_applied=failure.may_have_applied,
                    outcomes=[asdict(outcome)],
                    retry_after=failure.retry_after,
                )
            if not proposals.record_outcomes(user_id, proposal_id, [outcome], auth.clock()):
                return _outcomes(proposals.outcomes(user_id, proposal_id))
            return _outcomes([outcome])

    @app.exception_handler(AuthError)
    def auth_error(_request: Request, error: AuthError) -> JSONResponse:
        return authentication_error(error)

    @app.exception_handler(RequestValidationError)
    def invalid(_request: Request, _error_value: RequestValidationError) -> JSONResponse:
        return _error(400, "invalid_request", "Check the request fields.")

    @app.exception_handler(StepError)
    def provider_error(_request: Request, error: StepError) -> JSONResponse:
        return _error(
            PROVIDER_STATUS.get(error.code, 500),
            error.code,
            "The provider could not complete the read.",
        )

    @app.exception_handler(DocumentReadError)
    def document_error(_request: Request, error: DocumentReadError) -> JSONResponse:
        return _error(DOCUMENT_STATUS[error.code], error.code, "The document could not be read.")

    return app


def _run_action(
    workflow: Orchestrator, arguments: dict[str, object]
) -> tuple[ActionOutcome, ReviewMeetingError | None]:
    try:
        run = workflow.run(arguments)
    except ReviewMeetingError as error:
        log_failure(error)
        status: OutcomeStatus = (
            "uncertain" if error.may_have_applied or error.code == "outcome_unknown" else "failed"
        )
        return ActionOutcome(0, REVIEW_MEETING, status, error.body()), error
    return ActionOutcome(0, REVIEW_MEETING, "succeeded", run.body()), None


def authentication_error(error: AuthError) -> JSONResponse:
    message = (
        "Sign-in failed. Start again."
        if error.code == "invalid_sign_in"
        else "Sign in to continue."
    )
    if error.code == "origin_mismatch":
        message = "This request did not come from the signed-in site."
    response = _error(error.status, error.code, message)
    if error.status == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _outcomes(outcomes: list[ActionOutcome]) -> JSONResponse:
    return _reply({"outcomes": [asdict(outcome) for outcome in outcomes]})


def _error(
    status: int, code: str, message: str, *, retry_after: int | None = None, **details: object
) -> JSONResponse:
    response = _reply({"error": {"code": code, "message": message}, **details}, status)
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response


def _reply(content: dict[str, object], status: int = 200) -> JSONResponse:
    return JSONResponse(content, status_code=status, headers={"Cache-Control": "no-store"})

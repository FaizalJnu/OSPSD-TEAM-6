"""The agent service's HTTP API. The only module in the agent package that imports FastAPI.

Every endpoint acts for the user ``current_user`` returns. Sign-in provides it; until
it is wired, it fails closed with 401. Another user's IDs return 404, exactly like IDs
that do not exist. Errors use our body: ``{"error": {"code", "message"}}``.

    POST /v1/conversations                   {"time_zone": "America/New_York"}
    GET  /v1/conversations/{id}
    POST /v1/conversations/{id}/messages     {"text": ...}
    GET  /v1/proposals/{id}
    POST /v1/proposals/{id}/approve          {"proposal_hash": ...}
    POST /v1/proposals/{id}/reject

A request body over 16 KB, or a message over 4,000 characters, is 413. A user over
their message limit is 429 ``rate_limited``, and a run that does not fit the shared
token budget is 429 ``busy``; both set Retry-After and never call the model.
"""

import os
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from meeting_prep.agent.api_client import ActionOutcome
from meeting_prep.agent.http_api import HttpApiClient
from meeting_prep.agent.model import GroqModel
from meeting_prep.agent.model import Message as ChatMessage
from meeting_prep.agent.proposals import Proposal, proposal_view
from meeting_prep.agent.service import MESSAGE_CHARACTERS, AgentError, AgentService
from meeting_prep.api.sign_in import AuthError, SessionAuth, agent_principal, validate_origin
from meeting_prep.config import require
from meeting_prep.db import create_engine_for
from meeting_prep.db.agent_store import AgentStore
from meeting_prep.db.identity_store import IdentityStore

STATUS = {
    "invalid_request": 400,
    "unauthorized": 401,
    "not_found": 404,
    "payload_too_large": 413,
    "rate_limited": 429,
    "busy": 429,
    "stale_proposal": 409,
    "proposal_superseded": 409,
    "proposal_rejected": 409,
    "proposal_not_pending": 409,
    "approval_required": 409,
    "execution_failed": 502,
}


BODY_BYTES = 16 * 1024


class Unauthorized(Exception):
    pass


def current_user() -> str:
    """The signed-in user's internal ID. Sign-in replaces this; until then, nobody is."""
    raise Unauthorized


CurrentUser = Annotated[str, Depends(current_user)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewConversation(_Body):
    time_zone: str = Field(min_length=1, max_length=64, description="IANA, e.g. America/New_York")


class NewMessage(_Body):
    text: str = Field(min_length=1, max_length=MESSAGE_CHARACTERS)


class Approve(_Body):
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def create_live_app() -> FastAPI:
    engine = create_engine_for(require(os.environ, "DATABASE_URL"))
    auth = SessionAuth(IdentityStore(engine), require(os.environ, "PUBLIC_ORIGIN"))
    api_url = validate_origin(require(os.environ, "MEETING_API_URL"), "MEETING_API_URL")

    def session_for(user: str) -> str | None:
        principal = agent_principal.get()
        return principal.token if principal is not None and principal.user.id == user else None

    service = AgentService(
        AgentStore(engine), GroqModel.from_env(), HttpApiClient(api_url, session_for)
    )
    return create_app(service, auth=auth)


def create_app(service: AgentService, *, auth: SessionAuth | None = None) -> FastAPI:
    app = FastAPI(title="Meeting prep agent")
    app.add_middleware(BodyLimit, limit=BODY_BYTES)

    if auth is not None:
        session_auth = auth

        async def signed_in(request: Request) -> AsyncIterator[str]:
            principal = await run_in_threadpool(session_auth.require, request)
            context = agent_principal.set(principal)
            try:
                yield principal.user.id
            finally:
                agent_principal.reset(context)

        app.dependency_overrides[current_user] = signed_in

    @app.post("/v1/conversations", status_code=201)
    def create_conversation(body: NewConversation, user: CurrentUser) -> dict[str, object]:
        record = service.create_conversation(user, body.time_zone)
        return {
            "id": record.id,
            "time_zone": record.time_zone,
            "created_at": record.created_at.isoformat(),
            "messages": [],
            "pending_proposal": None,
        }

    @app.get("/v1/conversations/{conversation_id}")
    def get_conversation(conversation_id: str, user: CurrentUser) -> dict[str, object]:
        record, messages, pending = service.conversation(user, conversation_id)
        return {
            "id": record.id,
            "time_zone": record.time_zone,
            "created_at": record.created_at.isoformat(),
            "messages": _visible(messages),
            "pending_proposal": None if pending is None else proposal_view(pending),
        }

    @app.post("/v1/conversations/{conversation_id}/messages")
    async def send_message(
        conversation_id: str, body: NewMessage, user: CurrentUser
    ) -> dict[str, object]:
        reply = await service.send_message(user, conversation_id, body.text)
        return {
            "reply": reply.text,
            "stop_reason": reply.stop_reason,
            "run_id": reply.run_id,
            "proposal": None if reply.proposal is None else proposal_view(reply.proposal),
            "retry_after": reply.retry_after,
        }

    @app.get("/v1/proposals/{proposal_id}")
    def get_proposal(proposal_id: str, user: CurrentUser) -> dict[str, object]:
        return _with_outcomes(*service.proposal(user, proposal_id))

    @app.post("/v1/proposals/{proposal_id}/approve")
    async def approve(proposal_id: str, body: Approve, user: CurrentUser) -> dict[str, object]:
        return _with_outcomes(*await service.approve(user, proposal_id, body.proposal_hash))

    @app.post("/v1/proposals/{proposal_id}/reject")
    def reject(proposal_id: str, user: CurrentUser) -> dict[str, object]:
        return _with_outcomes(service.reject(user, proposal_id), [])

    @app.exception_handler(AgentError)
    def agent_error(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, AgentError)
        headers = None if error.retry_after is None else {"Retry-After": str(error.retry_after)}
        return _error(STATUS.get(error.code, 500), error.code, error.message, headers)

    @app.exception_handler(Unauthorized)
    def unauthorized(request: Request, error: Exception) -> JSONResponse:
        return _error(401, "unauthorized", "sign in to use the agent")

    @app.exception_handler(AuthError)
    def auth_error(request: Request, error: AuthError) -> JSONResponse:
        return _error(
            error.status, error.code, "A valid session from the signed-in site is required."
        )

    @app.exception_handler(RequestValidationError)
    def invalid(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, RequestValidationError)
        problem = error.errors()[0]
        if problem["type"] == "string_too_long" and problem["loc"][-1] == "text":
            return _too_large(f"text: at most {MESSAGE_CHARACTERS} characters")
        field = "body" if problem["type"] == "json_invalid" else problem["loc"][-1]
        return _error(400, "invalid_request", f"{field}: {problem['msg']}")

    @app.exception_handler(HTTPException)
    def http_error(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, HTTPException)
        if error.status_code == 404:
            return _error(404, "route_not_found", "no route matches this path")
        if error.status_code == 405:
            return _error(405, "method_not_allowed", f"this path does not accept {request.method}")
        return _error(error.status_code, "invalid_request", "the request could not be read")

    return app


def _error(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    content = {"error": {"code": code, "message": message}}
    return JSONResponse(status_code=status, content=content, headers=headers)


def _too_large(message: str) -> JSONResponse:
    return _error(413, "payload_too_large", message)


class _BodyTooLarge(Exception):
    pass


class BodyLimit:
    """Refuse a request body over ``limit`` bytes with 413, before anything reads it all.

    A declared Content-Length is checked first; a body without one is counted as it
    arrives.
    """

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            await self._refuse(scope, receive, send)
            return
        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.limit:
                raise _BodyTooLarge
            return message

        try:
            await self.app(scope, counted, send)
        except _BodyTooLarge:
            await self._refuse(scope, receive, send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = _too_large(f"the request body is over {self.limit} bytes")
        await response(scope, receive, send)


def _visible(messages: list[ChatMessage]) -> list[dict[str, object]]:
    """What a person sees of the conversation: their messages and the agent's answers."""
    return [
        {"role": message.role, "content": message.content}
        for message in messages
        if message.role in ("user", "assistant") and message.content
    ]


def _with_outcomes(proposal: Proposal, outcomes: list[ActionOutcome]) -> dict[str, object]:
    return {
        **proposal_view(proposal),
        "outcomes": [
            {"index": o.index, "kind": o.kind, "status": o.status, "detail": dict(o.detail)}
            for o in outcomes
        ],
    }

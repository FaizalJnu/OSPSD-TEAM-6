"""The agent service's HTTP API. The only module in the agent package that imports FastAPI.

Every endpoint acts for the user ``current_user`` returns. Sign-in provides it; until
it is wired, it fails closed with 401. Another user's IDs return 404, exactly like IDs
that do not exist. Errors use our body: ``{"error": {"code", "message"}}``.

    POST /v1/conversations
    GET  /v1/conversations/{id}
    POST /v1/conversations/{id}/messages     {"text": ...}
    GET  /v1/proposals/{id}
    POST /v1/proposals/{id}/approve          {"proposal_hash": ...}
    POST /v1/proposals/{id}/reject
"""

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException

from meeting_prep.agent.api_client import ActionOutcome
from meeting_prep.agent.model import Message
from meeting_prep.agent.proposals import Proposal, proposal_view
from meeting_prep.agent.service import MESSAGE_CHARACTERS, AgentError, AgentService

STATUS = {
    "invalid_request": 400,
    "unauthorized": 401,
    "not_found": 404,
    "stale_proposal": 409,
    "proposal_superseded": 409,
    "proposal_rejected": 409,
    "proposal_not_pending": 409,
    "approval_required": 409,
    "execution_failed": 502,
}


class Unauthorized(Exception):
    pass


def current_user() -> str:
    """The signed-in user's internal ID. Sign-in replaces this; until then, nobody is."""
    raise Unauthorized


CurrentUser = Annotated[str, Depends(current_user)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewMessage(_Body):
    text: str = Field(min_length=1, max_length=MESSAGE_CHARACTERS)


class Approve(_Body):
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def create_app(service: AgentService) -> FastAPI:
    app = FastAPI(title="Meeting prep agent")

    @app.post("/v1/conversations", status_code=201)
    def create_conversation(user: CurrentUser) -> dict[str, object]:
        record = service.create_conversation(user)
        return {
            "id": record.id,
            "created_at": record.created_at.isoformat(),
            "messages": [],
            "pending_proposal": None,
        }

    @app.get("/v1/conversations/{conversation_id}")
    def get_conversation(conversation_id: str, user: CurrentUser) -> dict[str, object]:
        record, messages, pending = service.conversation(user, conversation_id)
        return {
            "id": record.id,
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
        return _error(STATUS.get(error.code, 500), error.code, error.message)

    @app.exception_handler(Unauthorized)
    def unauthorized(request: Request, error: Exception) -> JSONResponse:
        return _error(401, "unauthorized", "sign in to use the agent")

    @app.exception_handler(RequestValidationError)
    def invalid(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, RequestValidationError)
        problem = error.errors()[0]
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


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _visible(messages: list[Message]) -> list[dict[str, object]]:
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

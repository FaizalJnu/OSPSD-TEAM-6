"""Calls to the agent service: conversations, messages, proposals, approvals.

The interface never approves or executes anything itself. It sends the agent
service the proposal hash the person saw, and the agent service and the API
check the approval. Every failure arrives as AgentError.
"""

from collections.abc import Callable
from typing import Any, Protocol

import httpx2 as httpx

from meeting_interface.agent_models import Conversation, MessageReply, Proposal
from meeting_interface.api_client import API_UNREACHABLE, BAD_RESPONSE


class AgentError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retry_after: int | None = None,
        may_have_applied: bool = False,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.may_have_applied = may_have_applied


class AgentClient(Protocol):
    def start_conversation(self, time_zone: str) -> Conversation: ...

    def send_message(self, conversation_id: str, text: str) -> MessageReply: ...

    def get_proposal(self, proposal_id: str) -> Proposal: ...

    def approve(self, proposal_id: str, proposal_hash: str) -> Proposal: ...

    def reject(self, proposal_id: str) -> Proposal: ...


class HttpAgentClient:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    @classmethod
    def for_url(cls, base_url: str, timeout_seconds: float = 120.0) -> "HttpAgentClient":
        return cls(httpx.Client(base_url=base_url, timeout=timeout_seconds))

    def start_conversation(self, time_zone: str) -> Conversation:
        body = {"time_zone": time_zone}
        return self._call("POST", "/v1/conversations", body, Conversation.from_json)

    def send_message(self, conversation_id: str, text: str) -> MessageReply:
        path = f"/v1/conversations/{conversation_id}/messages"
        return self._call("POST", path, {"text": text}, MessageReply.from_json)

    def get_proposal(self, proposal_id: str) -> Proposal:
        return self._call("GET", f"/v1/proposals/{proposal_id}", None, Proposal.from_json)

    def approve(self, proposal_id: str, proposal_hash: str) -> Proposal:
        path = f"/v1/proposals/{proposal_id}/approve"
        return self._call("POST", path, {"proposal_hash": proposal_hash}, Proposal.from_json)

    def reject(self, proposal_id: str) -> Proposal:
        return self._call("POST", f"/v1/proposals/{proposal_id}/reject", None, Proposal.from_json)

    def _call[T](
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        parse: Callable[[dict[str, Any]], T],
    ) -> T:
        try:
            response = self._http.request(method, path, json=body)
        except httpx.HTTPError as error:
            raise AgentError(API_UNREACHABLE, "the agent could not be reached") from error
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise _bad_response(response.status_code)
        try:
            if response.is_success:
                return parse(payload)
            failure = _error_from(payload, response)
        except (KeyError, TypeError, ValueError) as broken:
            raise _bad_response(response.status_code) from broken
        raise failure


def _error_from(payload: dict[str, Any], response: httpx.Response) -> AgentError:
    error = payload.get("error")
    if not isinstance(error, dict) or "code" not in error:
        return _bad_response(response.status_code)
    retry = response.headers.get("retry-after")
    return AgentError(
        str(error["code"]),
        str(error.get("message", "")),
        retry_after=int(retry) if retry is not None and retry.isdigit() else None,
        may_have_applied=error.get("may_have_applied") is True,
    )


def _bad_response(status: int) -> AgentError:
    return AgentError(BAD_RESPONSE, f"the agent sent an unexpected reply ({status})")

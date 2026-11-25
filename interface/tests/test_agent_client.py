"""HttpAgentClient speaks the agent service's API (product/docs/agent.md)."""

import json

import httpx2 as httpx
import pytest

from meeting_interface.agent_client import AgentError, HttpAgentClient
from meeting_interface.agent_models import OutcomeStatus

PROPOSAL = {
    "id": "p-1",
    "conversation_id": "c-1",
    "status": "pending",
    "proposal_hash": "ab12",
    "actions": [
        {
            "kind": "create_review_meeting",
            "operation": "POST /v1/review-meetings",
            "arguments": {
                "title": "Sprint review",
                "start": "2026-11-27T15:00:00-05:00",
                "end": "2026-11-27T15:30:00-05:00",
                "agenda": ["Open bugs"],
            },
        }
    ],
    "supersedes": None,
    "created_at": "2026-11-24T10:00:00+00:00",
}


def client_for(handler) -> HttpAgentClient:
    http = httpx.Client(base_url="https://agent.test", transport=httpx.MockTransport(handler))
    return HttpAgentClient(http)


def respond(status: int, body: object, headers: dict[str, str] | None = None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body, headers=headers)

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


def test_start_conversation_sends_the_time_zone():
    handler = respond(
        201,
        {"id": "c-1", "time_zone": "America/New_York", "messages": [], "pending_proposal": None},
    )

    conversation = client_for(handler).start_conversation("America/New_York")

    request = handler.seen[0]
    assert (request.method, request.url.path) == ("POST", "/v1/conversations")
    assert json.loads(request.content) == {"time_zone": "America/New_York"}
    assert conversation.id == "c-1"
    assert conversation.pending_proposal is None


def test_send_message_reads_reply_and_proposal():
    handler = respond(
        200,
        {
            "reply": "Here is the plan.",
            "stop_reason": "completed",
            "run_id": "r-1",
            "proposal": PROPOSAL,
            "retry_after": None,
        },
    )

    reply = client_for(handler).send_message("c-1", "prep my Friday review")

    request = handler.seen[0]
    assert request.url.path == "/v1/conversations/c-1/messages"
    assert json.loads(request.content) == {"text": "prep my Friday review"}
    assert reply.text == "Here is the plan."
    assert reply.stop_reason == "completed"
    assert reply.proposal is not None
    assert reply.proposal.proposal_hash == "ab12"
    assert reply.proposal.actions[0].arguments["title"] == "Sprint review"


def test_a_run_that_stopped_early_has_no_reply():
    handler = respond(
        200,
        {
            "reply": None,
            "stop_reason": "token_limit",
            "run_id": "r-2",
            "proposal": None,
            "retry_after": None,
        },
    )

    reply = client_for(handler).send_message("c-1", "hello")

    assert reply.text is None
    assert reply.stop_reason == "token_limit"


def test_approve_sends_the_hash_that_was_shown_and_reads_outcomes():
    handler = respond(
        200,
        {
            **PROPOSAL,
            "status": "executed",
            "outcomes": [
                {
                    "index": 0,
                    "kind": "create_review_meeting",
                    "status": "succeeded",
                    "detail": {"run_id": "3f9a1c0d7b2e"},
                },
            ],
        },
    )

    proposal = client_for(handler).approve("p-1", "ab12")

    request = handler.seen[0]
    assert request.url.path == "/v1/proposals/p-1/approve"
    assert json.loads(request.content) == {"proposal_hash": "ab12"}
    assert proposal.status == "executed"
    assert proposal.outcomes[0].status is OutcomeStatus.SUCCEEDED


def test_reject_posts_to_reject():
    handler = respond(200, {**PROPOSAL, "status": "rejected", "outcomes": []})

    proposal = client_for(handler).reject("p-1")

    assert handler.seen[0].url.path == "/v1/proposals/p-1/reject"
    assert proposal.status == "rejected"


def test_unknown_outcome_status_is_uncertain_never_succeeded():
    handler = respond(
        200,
        {
            **PROPOSAL,
            "status": "executed",
            "outcomes": [{"index": 0, "kind": "x", "status": "maybe", "detail": {}}],
        },
    )

    proposal = client_for(handler).approve("p-1", "ab12")

    assert proposal.outcomes[0].status is OutcomeStatus.UNCERTAIN


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (409, "stale_proposal"),
        (409, "proposal_superseded"),
        (502, "execution_failed"),
        (404, "not_found"),
        (401, "unauthorized"),
    ],
)
def test_error_body_becomes_agent_error(status, code):
    handler = respond(status, {"error": {"code": code, "message": f"about {code}"}})

    with pytest.raises(AgentError) as caught:
        client_for(handler).approve("p-1", "ab12")

    assert caught.value.code == code
    assert caught.value.message == f"about {code}"


def test_rate_limit_reads_retry_after():
    handler = respond(429, {"error": {"code": "busy", "message": "busy"}}, {"Retry-After": "42"})

    with pytest.raises(AgentError) as caught:
        client_for(handler).send_message("c-1", "hello")

    assert caught.value.code == "busy"
    assert caught.value.retry_after == 42


def test_execution_failed_keeps_may_have_applied():
    body = {"error": {"code": "execution_failed", "message": "x", "may_have_applied": True}}

    with pytest.raises(AgentError) as caught:
        client_for(respond(502, body)).approve("p-1", "ab12")

    assert caught.value.may_have_applied is True


def test_unreachable_and_unreadable_replies():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AgentError) as unreachable:
        client_for(down).reject("p-1")
    with pytest.raises(AgentError) as garbled:
        client_for(lambda r: httpx.Response(502, text="<html>")).reject("p-1")

    assert unreachable.value.code == "api_unreachable"
    assert garbled.value.code == "bad_response"

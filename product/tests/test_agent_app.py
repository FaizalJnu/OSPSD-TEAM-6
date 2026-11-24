"""The agent service over HTTP: conversations, proposals, approvals, restarts, records, isolation.

Each test runs the real app on a SQLite database built by the migrations, with the
scripted model and the fake API client. No network.
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from meeting_prep.agent.api_client import ApiError
from meeting_prep.agent.app import create_app, current_user
from meeting_prep.agent.loop import Limits
from meeting_prep.agent.model import ModelError, ScriptedModel, ScriptStep
from meeting_prep.agent.proposals import (
    REVIEW_MEETING,
    Action,
    Approval,
    approval_matches,
    canonical_json,
    proposal_hash,
)
from meeting_prep.agent.service import DEFAULT_LIMITS, AgentError, AgentService, system_prompt
from meeting_prep.db import create_engine_for, upgrade
from meeting_prep.db.agent_store import AgentStore
from tests.fake_api import FakeApi

NOW = datetime(2026, 11, 18, 21, 0, tzinfo=UTC)
MEETING = {
    "title": "Sprint 12 review",
    "start": "2026-11-20T15:00:00-05:00",
    "end": "2026-11-20T15:30:00-05:00",
    "agenda": ["Open bugs"],
}
answer, call = ScriptedModel.answer, ScriptedModel.call


def propose(meeting: dict[str, Any] = MEETING, id: str = "call-1") -> list[ScriptStep]:
    return [call("propose_review_meeting", json.dumps(meeting), id=id), answer("Proposed.")]


@pytest.fixture
def db_url(tmp_path) -> str:
    url = f"sqlite:///{tmp_path / 'agent.sqlite3'}"
    upgrade(url)
    return url


class Agent:
    """One instance of the agent service: its own engine, model and app."""

    def __init__(
        self, url: str, script: list[ScriptStep], api: FakeApi, limits: Limits = DEFAULT_LIMITS
    ) -> None:
        self.store = AgentStore(create_engine_for(url))
        self.model = ScriptedModel(script)
        self.service = AgentService(self.store, self.model, api, limits=limits, now=lambda: NOW)
        self.app = create_app(self.service)

    def client(self, user: str | None = "user-a") -> TestClient:
        self.app.dependency_overrides.clear()
        if user is not None:
            self.app.dependency_overrides[current_user] = lambda: user
        return TestClient(self.app)

    def conversation(self, user: str = "user-a") -> str:
        response = self.client(user).post("/v1/conversations")
        assert response.status_code == 201
        conversation_id: str = response.json()["id"]
        return conversation_id

    def say(self, conversation_id: str, text: str, user: str = "user-a") -> dict[str, Any]:
        response = self.client(user).post(
            f"/v1/conversations/{conversation_id}/messages", json={"text": text}
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


def error_code(response: Any) -> str:
    code: str = response.json()["error"]["code"]
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message"}
    return code


# --- Conversations and the loop ---


def test_a_conversation_starts_empty(db_url, api):
    agent = Agent(db_url, [], api)

    created = agent.client().post("/v1/conversations")
    fetched = agent.client().get(f"/v1/conversations/{created.json()['id']}")

    assert created.status_code == 201
    assert created.json()["messages"] == [] and created.json()["pending_proposal"] is None
    assert fetched.status_code == 200
    assert fetched.json() == {**created.json(), "created_at": fetched.json()["created_at"]}


def test_a_message_runs_the_loop_with_the_system_prompt_and_saves_the_exchange(db_url, api):
    agent = Agent(db_url, [call("list_open_issues", "{}"), answer("Two issues are open.")], api)
    conversation = agent.conversation()

    reply = agent.say(conversation, "What is open?")

    assert reply["reply"] == "Two issues are open."
    assert reply["stop_reason"] == "completed" and reply["proposal"] is None
    sent = agent.model.calls[0]
    assert sent.messages[0].role == "system" and sent.messages[0].content == system_prompt()
    assert sent.max_tokens == 6_000
    assert api.calls == [("list_open_issues", "user-a", 20)]
    shown = agent.client().get(f"/v1/conversations/{conversation}").json()["messages"]
    assert shown == [
        {"role": "user", "content": "What is open?"},
        {"role": "assistant", "content": "Two issues are open."},
    ]


def test_the_next_message_sends_the_whole_history_back(db_url, api):
    agent = Agent(db_url, [call("list_open_issues", "{}"), answer("Two."), answer("Yes.")], api)
    conversation = agent.conversation()
    agent.say(conversation, "What is open?")

    agent.say(conversation, "Is that all?")

    roles = [message.role for message in agent.model.calls[2].messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "user"]


def test_tool_calls_a_run_stopped_before_are_answered_so_the_history_stays_valid(db_url, api):
    from meeting_prep.agent.model import ModelResponse, ToolCall, Usage

    two = ModelResponse(
        None,
        (ToolCall("a", "list_open_issues", "{}"), ToolCall("b", "list_upcoming_events", "{}")),
        Usage(10, 5),
        "scripted",
        "tool_calls",
    )
    agent = Agent(db_url, [two, answer("ok")], api, limits=Limits(max_steps=1))
    conversation = agent.conversation()

    assert agent.say(conversation, "Prepare.")["stop_reason"] == "max_steps"
    agent.say(conversation, "Go on.")

    history = agent.model.calls[1].messages
    answered = {m.tool_call_id: m.content for m in history if m.role == "tool"}
    assert set(answered) == {"a", "b"}
    assert json.loads(str(answered["b"]))["error"]["code"] == "not_run"


# --- Proposals and approvals ---


def proposed(agent: Agent, user: str = "user-a") -> tuple[str, dict[str, Any]]:
    conversation = agent.conversation(user)
    reply = agent.say(conversation, "Book the sprint 12 review.", user)
    assert reply["proposal"] is not None
    return conversation, reply["proposal"]


def test_propose_approve_execute(db_url, api):
    agent = Agent(db_url, propose(), api)
    conversation, proposal = proposed(agent)

    assert proposal["status"] == "pending" and proposal["conversation_id"] == conversation
    assert proposal["actions"] == [
        {
            "kind": REVIEW_MEETING,
            "arguments": MEETING,
            "operation": "POST /v1/review-meetings",
        }
    ]
    assert api.executed() == []  # proposing executes nothing
    fetched = agent.client().get(f"/v1/proposals/{proposal['id']}")
    assert fetched.status_code == 200 and fetched.json()["outcomes"] == []

    approved = agent.client().post(
        f"/v1/proposals/{proposal['id']}/approve", json={"proposal_hash": proposal["proposal_hash"]}
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "executed"
    assert approved.json()["outcomes"] == [
        {
            "index": 0,
            "kind": REVIEW_MEETING,
            "status": "succeeded",
            "detail": {"run_id": "3f9a1c0d7b2e", "status": "succeeded"},
        }
    ]
    assert api.executed() == [("user-a", proposal["id"])]
    pending = agent.client().get(f"/v1/conversations/{conversation}").json()["pending_proposal"]
    assert pending is None


def test_reject(db_url, api):
    agent = Agent(db_url, propose(), api)
    _, proposal = proposed(agent)
    path = f"/v1/proposals/{proposal['id']}"

    rejected = agent.client().post(f"{path}/reject")
    again = agent.client().post(f"{path}/reject")
    approve = agent.client().post(
        f"{path}/approve", json={"proposal_hash": proposal["proposal_hash"]}
    )

    assert rejected.status_code == again.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert approve.status_code == 409 and error_code(approve) == "proposal_rejected"
    assert api.executed() == []


def test_an_executed_proposal_cannot_be_rejected(db_url, api):
    agent = Agent(db_url, propose(), api)
    _, proposal = proposed(agent)
    path = f"/v1/proposals/{proposal['id']}"
    agent.client().post(f"{path}/approve", json={"proposal_hash": proposal["proposal_hash"]})

    response = agent.client().post(f"{path}/reject")

    assert response.status_code == 409 and error_code(response) == "proposal_not_pending"


def test_a_stale_hash_is_refused(db_url, api):
    agent = Agent(db_url, propose(), api)
    _, proposal = proposed(agent)

    response = agent.client().post(
        f"/v1/proposals/{proposal['id']}/approve", json={"proposal_hash": "0" * 64}
    )

    assert response.status_code == 409 and error_code(response) == "stale_proposal"
    assert api.executed() == []
    assert agent.client().get(f"/v1/proposals/{proposal['id']}").json()["status"] == "pending"


def test_a_changed_proposal_supersedes_the_old_one_and_needs_its_own_approval(db_url, api):
    later = {**MEETING, "end": "2026-11-20T16:00:00-05:00"}
    agent = Agent(db_url, [*propose(), *propose(later, id="call-2")], api)
    conversation, first = proposed(agent)

    second = agent.say(conversation, "Make it an hour.")["proposal"]
    old = agent.client().post(
        f"/v1/proposals/{first['id']}/approve", json={"proposal_hash": first["proposal_hash"]}
    )

    assert second["id"] != first["id"] and second["proposal_hash"] != first["proposal_hash"]
    assert second["supersedes"] == first["id"]
    assert agent.client().get(f"/v1/proposals/{first['id']}").json()["status"] == "superseded"
    assert old.status_code == 409 and error_code(old) == "proposal_superseded"
    assert api.executed() == []
    new = agent.client().post(
        f"/v1/proposals/{second['id']}/approve", json={"proposal_hash": second["proposal_hash"]}
    )
    assert new.json()["status"] == "executed"
    assert api.executed() == [("user-a", second["id"])]


def test_execute_without_an_approval_is_refused(db_url, api):
    agent = Agent(db_url, propose(), api)
    _, proposal = proposed(agent)

    with pytest.raises(AgentError) as error:
        asyncio.run(agent.service.execute("user-a", proposal["id"]))

    assert error.value.code == "approval_required"
    assert api.executed() == []


def test_a_retry_after_the_stored_proposal_changed_is_refused(db_url, api):
    from sqlalchemy import update

    from meeting_prep.db.tables.agent import ProposalRow

    agent = Agent(db_url, propose(), api)
    _, proposal = proposed(agent)
    body = {"proposal_hash": proposal["proposal_hash"]}
    api.failures["execute"] = ApiError("provider_unavailable", "down")
    agent.client().post(f"/v1/proposals/{proposal['id']}/approve", json=body)
    # Someone changes the approved proposal's actions in the database.
    changed = [{"kind": REVIEW_MEETING, "arguments": {**MEETING, "title": "Something else"}}]
    with agent.store.engine.begin() as connection:
        connection.execute(
            update(ProposalRow).where(ProposalRow.id == proposal["id"]).values(actions=changed)
        )

    with pytest.raises(AgentError) as error:
        asyncio.run(agent.service.execute("user-a", proposal["id"]))

    assert error.value.code == "approval_required"
    assert len(api.executed()) == 1  # only the first, failed call


def test_an_approval_matches_only_its_proposal_hash_and_user():
    actions = (Action(REVIEW_MEETING, MEETING),)
    digest = proposal_hash("user-a", actions)
    from meeting_prep.agent.proposals import Proposal

    proposal = Proposal("p1", "user-a", "c1", actions, digest, "approved", NOW)
    good = Approval("a1", "p1", digest, "user-a", NOW)

    assert approval_matches(good, proposal, "user-a")
    assert not approval_matches(None, proposal, "user-a")
    assert not approval_matches(Approval("a1", "p2", digest, "user-a", NOW), proposal, "user-a")
    assert not approval_matches(Approval("a1", "p1", "0" * 64, "user-a", NOW), proposal, "user-a")
    assert not approval_matches(Approval("a1", "p1", digest, "user-b", NOW), proposal, "user-b")
    changed = Proposal("p1", "user-a", "c1", (Action(REVIEW_MEETING, {}),), digest, "approved", NOW)
    assert not approval_matches(good, changed, "user-a")  # contents no longer match the hash


def test_the_hash_is_sha256_over_the_canonical_json():
    actions = (Action(REVIEW_MEETING, {"b": 1, "a": "é"}),)

    assert (
        canonical_json("user-a", actions)
        == (
            '{"actions":[{"arguments":{"a":"é","b":1},"kind":"create_review_meeting"}],'
            '"user_id":"user-a"}'
        ).encode()
    )
    assert len(proposal_hash("user-a", actions)) == 64


def test_a_failed_execute_keeps_the_approval_and_approving_again_retries(db_url, api):
    agent = Agent(db_url, propose(), api)
    _, proposal = proposed(agent)
    body = {"proposal_hash": proposal["proposal_hash"]}
    api.failures["execute"] = ApiError("provider_unavailable", "down", may_have_applied=True)

    failed = agent.client().post(f"/v1/proposals/{proposal['id']}/approve", json=body)
    retried = agent.client().post(f"/v1/proposals/{proposal['id']}/approve", json=body)

    assert failed.status_code == 502 and error_code(failed) == "execution_failed"
    assert "may have been partly applied" in failed.json()["error"]["message"]
    assert retried.status_code == 200 and retried.json()["status"] == "executed"
    assert len(api.executed()) == 2  # the failed call, then the retry


# --- Restart ---


def test_a_pending_approval_survives_a_restart_and_is_never_executed_twice(db_url, api):
    first = Agent(db_url, propose(), api)
    _, proposal = proposed(first)
    body = {"proposal_hash": proposal["proposal_hash"]}

    restarted = Agent(db_url, [], api)  # a new process on the same database
    pending = restarted.client().get(f"/v1/proposals/{proposal['id']}")
    approved = restarted.client().post(f"/v1/proposals/{proposal['id']}/approve", json=body)
    again = (
        Agent(db_url, [], api).client().post(f"/v1/proposals/{proposal['id']}/approve", json=body)
    )

    assert pending.json()["status"] == "pending"
    assert approved.json()["status"] == "executed"
    assert again.status_code == 200 and again.json() == approved.json()  # the stored outcome
    assert len(api.executed()) == 1


# --- Execution records ---


def test_a_failed_run_is_explained_by_its_record_and_holds_no_secrets(db_url, api):
    script: list[ScriptStep] = [
        call("read_document", json.dumps({"path": "/reviews/notes.md"}), id="read"),
        call("delete_everything", "{}", id="unknown"),
        call("list_open_issues", json.dumps({"limit": 500}), id="bad"),
        ModelError("the model request failed (InternalServerError, 500)"),
    ]
    agent = Agent(db_url, script, api)
    conversation = agent.conversation()

    reply = agent.say(conversation, "My Trello token is tok-SECRET-999; prepare the review.")
    record = agent.store.get_run("user-a", reply["run_id"])

    assert reply["stop_reason"] == "model_error" and reply["reply"] is None
    assert record is not None
    assert record["stop_reason"] == "model_error"
    assert record["error"] == "the model request failed (InternalServerError, 500)"
    assert (record["model"], record["prompt_version"], record["model_calls"]) == (
        "scripted",
        "system_v1",
        3,
    )
    assert (record["prompt_tokens"], record["completion_tokens"]) == (30, 15)
    assert [step["tool"] for step in record["steps"]] == [
        "read_document",
        "delete_everything",
        "list_open_issues",
    ]
    assert record["steps"][0]["result"]["content"] == "<18 characters>"
    assert [d["decision"] for d in record["policy_decisions"]] == [
        "refused_unknown_tool",
        "rejected_arguments",
    ]
    assert record["policy_decisions"][1]["problems"][0]["loc"] == ["limit"]
    assert record["started_at"] <= record["ended_at"]
    text = json.dumps(record, default=str)
    for secret in ("tok-SECRET-999", FakeApi.token, "ship it", "500}"):
        assert secret not in text


def test_a_proposal_is_recorded_as_a_policy_decision(db_url, api):
    agent = Agent(db_url, propose(), api)
    conversation = agent.conversation()

    reply = agent.say(conversation, "Book it.")
    record = agent.store.get_run("user-a", reply["run_id"])

    assert record is not None
    assert record["policy_decisions"] == [
        {
            "decision": "approval_required",
            "proposal_id": reply["proposal"]["id"],
            "proposal_hash": reply["proposal"]["proposal_hash"],
            "superseded": None,
        }
    ]


# --- Isolation ---


def test_user_b_cannot_read_or_act_on_user_as_conversation_or_proposal(db_url, api):
    agent = Agent(db_url, propose(), api)
    conversation, proposal = proposed(agent, "user-a")
    b = agent.client("user-b")
    body = {"proposal_hash": proposal["proposal_hash"]}

    responses = [
        b.get(f"/v1/conversations/{conversation}"),
        b.post(f"/v1/conversations/{conversation}/messages", json={"text": "hi"}),
        b.get(f"/v1/proposals/{proposal['id']}"),
        b.post(f"/v1/proposals/{proposal['id']}/approve", json=body),
        b.post(f"/v1/proposals/{proposal['id']}/reject"),
    ]

    assert [r.status_code for r in responses] == [404] * 5
    assert {error_code(r) for r in responses} == {"not_found"}
    assert len(agent.model.calls) == 2  # only A's run called the model
    assert api.executed() == []
    a = agent.client("user-a").get(f"/v1/proposals/{proposal['id']}")
    assert a.json()["status"] == "pending"
    stored = agent.store.pending_proposal("user-a", conversation)
    assert stored is not None and stored.run_id is not None
    assert agent.store.get_run("user-b", stored.run_id) is None  # nor A's run record


def test_tools_read_only_the_signed_in_users_data(db_url, api):
    agent = Agent(db_url, [call("list_open_issues", "{}"), answer("One.")], api)
    conversation = agent.conversation("user-b")

    agent.say(conversation, "What is open?", "user-b")

    assert api.calls == [("list_open_issues", "user-b", 20)]


# --- HTTP errors ---

ENDPOINTS = [
    ("post", "/v1/conversations", None),
    ("get", "/v1/conversations/c1", None),
    ("post", "/v1/conversations/c1/messages", {"text": "hi"}),
    ("get", "/v1/proposals/p1", None),
    ("post", "/v1/proposals/p1/approve", {"proposal_hash": "a" * 64}),
    ("post", "/v1/proposals/p1/reject", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
def test_every_endpoint_is_401_without_a_signed_in_user(db_url, api, method, path, body):
    response = Agent(db_url, [], api).client(None).request(method, path, json=body)

    assert response.status_code == 401 and error_code(response) == "unauthorized"


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS[1:])
def test_an_unknown_id_is_404(db_url, api, method, path, body):
    response = Agent(db_url, [], api).client().request(method, path, json=body)

    assert response.status_code == 404 and error_code(response) == "not_found"


@pytest.mark.parametrize(
    ("path", "body", "field"),
    [
        ("messages", {"text": ""}, "text"),
        ("messages", {"text": "x" * 4001}, "text"),
        ("messages", {"text": "hi", "user": "user-b"}, "user"),
        ("messages", None, "body"),
        ("approve", {"proposal_hash": "not-a-hash"}, "proposal_hash"),
        ("approve", {}, "proposal_hash"),
    ],
)
def test_an_invalid_body_is_400_and_names_the_field(db_url, api, path, body, field):
    agent = Agent(db_url, [], api)
    conversation = agent.conversation()
    url = (
        f"/v1/conversations/{conversation}/messages"
        if path == "messages"
        else "/v1/proposals/p1/approve"
    )

    response = agent.client().post(url, json=body)

    assert response.status_code == 400 and error_code(response) == "invalid_request"
    assert response.json()["error"]["message"].startswith(f"{field}: ")
    assert agent.model.calls == []


def test_a_body_that_is_not_json_is_400(db_url, api):
    agent = Agent(db_url, [], api)
    conversation = agent.conversation()

    response = agent.client().post(
        f"/v1/conversations/{conversation}/messages",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"].startswith("body: ")


def test_an_unknown_route_and_method_use_our_error_body(db_url, api):
    client = Agent(db_url, [], api).client()

    missing, wrong = client.get("/v1/nothing"), client.delete("/v1/conversations")

    assert missing.status_code == 404 and error_code(missing) == "route_not_found"
    assert wrong.status_code == 405 and error_code(wrong) == "method_not_allowed"

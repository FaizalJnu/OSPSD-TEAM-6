"""The two deterministic agent cases the other agent tests do not cover (team plan, row D).

Clarification, and a provider error reaching the model through a tool. Like the
rest of the agent tests, they run the real service and app on a SQLite database,
with the scripted model and the fake API: no network, no live model. TESTING.md
maps every deterministic case to its test.
"""

import json

import pytest

from meeting_prep.agent.api_client import ApiError
from meeting_prep.db import upgrade
from tests.fake_api import FakeApi
from tests.test_agent_app import MEETING, Agent, answer, call

QUESTION = "Which review do you mean: Sprint 12 or Sprint 13?"


@pytest.fixture
def db_url(tmp_path) -> str:
    url = f"sqlite:///{tmp_path / 'agent.sqlite3'}"
    upgrade(url)
    return url


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


def test_clarification_asks_first_and_proposes_only_after_the_answer(db_url, api):
    agent = Agent(
        db_url,
        [
            answer(QUESTION),
            call("propose_review_meeting", json.dumps(MEETING), id="call-1"),
            answer("Here is the Sprint 12 review. Approve it to go ahead."),
        ],
        api,
    )
    conversation = agent.conversation()

    asked = agent.say(conversation, "Prepare the review.")

    assert asked["reply"] == QUESTION
    assert asked["stop_reason"] == "completed"
    assert asked["proposal"] is None
    pending = agent.client().get(f"/v1/conversations/{conversation}").json()["pending_proposal"]
    assert pending is None
    assert api.executed() == []

    answered = agent.say(conversation, "Sprint 12")

    assert answered["proposal"] is not None
    assert answered["proposal"]["status"] == "pending"
    assert answered["proposal"]["actions"][0]["arguments"]["title"] == MEETING["title"]
    assert api.executed() == []  # proposed, still not executed: approval comes first
    history = [(m.role, m.content) for m in agent.model.calls[1].messages]
    assert ("user", "Prepare the review.") in history
    assert ("assistant", QUESTION) in history
    assert ("user", "Sprint 12") in history


def test_a_provider_error_through_a_tool_reaches_the_model_and_nothing_is_written(db_url, api):
    api.failures["list_open_issues"] = ApiError(
        "provider_unavailable", "The issue tracker could not be reached."
    )
    agent = Agent(
        db_url,
        [
            call("list_open_issues", "{}", id="call-1"),
            answer("The issue tracker is unavailable right now. Try again in a few minutes."),
        ],
        api,
    )
    conversation = agent.conversation()

    reply = agent.say(conversation, "What is open?")

    assert reply["reply"].startswith("The issue tracker is unavailable")
    assert reply["stop_reason"] == "completed"
    assert reply["proposal"] is None
    assert api.executed() == []
    tool_results = [
        json.loads(str(m.content)) for m in agent.model.calls[1].messages if m.role == "tool"
    ]
    assert len(tool_results) == 1
    assert tool_results[0]["error"]["code"] == "provider_unavailable"
    # The run record explains the failure by its code, so it can be diagnosed later.
    record = agent.store.get_run("user-a", reply["run_id"])
    assert record is not None
    assert "provider_unavailable" in json.dumps(record, default=str)

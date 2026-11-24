"""The meeting tools: argument validation, result shapes and failures. No model, no network."""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from meeting_prep.agent.api_client import ApiError
from meeting_prep.agent.proposals import REVIEW_MEETING, Action, Proposal, proposal_hash
from meeting_prep.agent.tools import InvalidArguments, ToolError, result_json
from meeting_prep.agent.tools_meeting import DOCUMENT_CHARACTERS, meeting_tools
from tests.fake_api import FakeApi

NOW = datetime(2026, 11, 18, 21, 0, tzinfo=UTC)
MEETING = {
    "title": "  Sprint 12 review ",
    "start": "2026-11-20T15:00:00-05:00",
    "end": "2026-11-20T15:30:00-05:00",
    "agenda": ["Open bugs", "Release go or no-go"],
}


class Harness:
    def __init__(self) -> None:
        self.api = FakeApi()
        self.proposed: list[tuple[Action, ...]] = []
        self.registry = meeting_tools(self.api, "user-a", self.propose, lambda: NOW)

    def propose(self, actions: tuple[Action, ...]) -> Proposal:
        self.proposed.append(actions)
        return Proposal(
            "p1", "user-a", "c1", actions, proposal_hash("user-a", actions), "pending", NOW
        )

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, object]:
        tool, args = self.registry.validate(name, json.dumps(arguments))
        return result_json(asyncio.run(tool.handler(args)))


@pytest.fixture
def tools() -> Harness:
    return Harness()


def test_the_four_tools_and_their_schemas(tools):
    specs = {spec.name: spec for spec in tools.registry.specs()}

    assert set(specs) == {
        "list_open_issues",
        "list_upcoming_events",
        "read_document",
        "propose_review_meeting",
    }
    propose = specs["propose_review_meeting"].parameters
    assert propose["required"] == ["title", "start", "end"]
    assert propose["additionalProperties"] is False


def test_list_open_issues_reads_as_the_user(tools):
    assert tools.call("list_open_issues", {"limit": 1}) == {
        "issues": [{"id": "card-2", "title": "Release checklist"}]
    }
    assert tools.api.calls == [("list_open_issues", "user-a", 1)]


def test_list_upcoming_events_reads_as_the_user(tools):
    result = tools.call("list_upcoming_events", {})

    assert result == {
        "events": [
            {
                "id": "evt-1",
                "title": "Sprint review",
                "start": "2026-11-20T20:00:00Z",
                "end": "2026-11-20T20:30:00Z",
            }
        ]
    }
    assert tools.api.calls == [("list_upcoming_events", "user-a", 14)]


def test_read_document_returns_the_content_and_cuts_a_long_one(tools):
    assert tools.call("read_document", {"path": "/reviews/notes.md"}) == {
        "path": "/reviews/notes.md",
        "content": "# Notes\n- ship it\n",
        "truncated": False,
    }
    tools.api.documents[("user-a", "/big.md")] = "x" * (DOCUMENT_CHARACTERS + 5)

    big = tools.call("read_document", {"path": "/big.md"})

    assert big["truncated"] is True and len(str(big["content"])) == DOCUMENT_CHARACTERS


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("list_open_issues", {"limit": 0}),
        ("list_open_issues", {"limit": 101}),
        ("list_open_issues", {"user": "user-b"}),  # no way to name another user
        ("list_upcoming_events", {"days": 61}),
        ("read_document", {"path": ""}),
        ("read_document", {"path": "/a\nb.md"}),
        ("propose_review_meeting", {**MEETING, "title": "   "}),
        ("propose_review_meeting", {**MEETING, "title": "x" * 121}),
        ("propose_review_meeting", {**MEETING, "start": "2026-11-20T15:00:00"}),  # no offset
        ("propose_review_meeting", {**MEETING, "start": "2026-11-20T15:00:00.5Z"}),
        ("propose_review_meeting", {**MEETING, "end": "2026-11-20T14:00:00-05:00"}),
        ("propose_review_meeting", {**MEETING, "end": "2026-11-21T00:00:01-05:00"}),  # > 8 h
        ("propose_review_meeting", {**MEETING, "agenda": [""]}),
        ("propose_review_meeting", {**MEETING, "agenda": ["x"] * 21}),
        ("propose_review_meeting", {**MEETING, "execute_now": True}),
    ],
)
def test_invalid_arguments_are_refused_before_the_handler_runs(tools, name, arguments):
    with pytest.raises(InvalidArguments):
        tools.registry.validate(name, json.dumps(arguments))

    assert tools.api.calls == [] and tools.proposed == []


def test_an_api_failure_is_a_tool_error_with_the_apis_code(tools):
    tools.api.failures["list_open_issues"] = ApiError("provider_unavailable", "tracker is down")

    with pytest.raises(ToolError) as error:
        tools.call("list_open_issues", {})

    assert (error.value.code, error.value.message) == ("provider_unavailable", "tracker is down")


def test_reading_a_missing_document_is_not_found(tools):
    with pytest.raises(ToolError) as error:
        tools.call("read_document", {"path": "/nope.md"})

    assert error.value.code == "not_found"


def test_propose_review_meeting_creates_a_proposal_and_executes_nothing(tools):
    result = tools.call("propose_review_meeting", MEETING)

    (actions,) = tools.proposed
    assert actions == (
        Action(
            REVIEW_MEETING,
            {
                "title": "Sprint 12 review",  # trimmed
                "start": "2026-11-20T15:00:00-05:00",
                "end": "2026-11-20T15:30:00-05:00",
                "agenda": ["Open bugs", "Release go or no-go"],
            },
        ),
    )
    assert result["status"] == "pending_approval"
    assert result["operation"] == "POST /v1/review-meetings"
    assert result["proposal_id"] == "p1"
    assert result["proposal_hash"] == proposal_hash("user-a", actions)
    assert isinstance(result["effects"], list) and len(result["effects"]) == 3
    assert tools.api.calls == []  # nothing executed, nothing read


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-11-18T20:00:00Z", "2026-11-18T20:30:00Z"),
        ("2027-11-19T21:00:00Z", "2027-11-19T21:30:00Z"),
    ],
    ids=["in the past", "more than 365 days ahead"],
)
def test_propose_refuses_a_start_outside_the_next_365_days(tools, start, end):
    with pytest.raises(ToolError) as error:
        tools.call("propose_review_meeting", {**MEETING, "start": start, "end": end})

    assert error.value.code == "invalid_time"
    assert tools.proposed == []

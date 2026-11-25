"""Exercise the fixed workflow through HTTP, using the configured adapter boundary."""

import json
from datetime import UTC, datetime

import pytest
from calendar_contract import CalendarError
from calendar_contract import ErrorCode as CalendarCode
from fastapi.testclient import TestClient
from issue_tracker_contract import ErrorCode, Issue, ServiceError

from meeting_prep.adapters.calendar import EventCalendarAdapter
from meeting_prep.adapters.storage import DocumentStorageAdapter
from meeting_prep.adapters.tracker import IssueTrackerAdapter
from meeting_prep.api.main import MAX_REQUEST_BYTES, build_app
from meeting_prep.fakes import FakeCalendar, FakeStorage, FakeTracker
from meeting_prep.orchestrator import Orchestrator

_HEADERS = {"Authorization": "Bearer test-key"}
_REQUEST = {
    "title": "private meeting title",
    "start": "2026-11-25T18:00:00Z",
    "end": "2026-11-25T19:00:00Z",
    "agenda": ["private agenda item"],
}


class TaggedTracker(FakeTracker):
    """Model token lookup independently of titles and the list of open issues."""

    def __init__(self) -> None:
        super().__init__()
        self.tokens: dict[str, Issue] = {}
        self.queries: list[str] = []
        self.attempts = 0
        self.lose_response = False
        self.lose_lookup = False

    def create_tagged_issue(self, title: str, creation_token: str) -> Issue:
        self.attempts += 1
        issue = super().create_issue(title)
        self.tokens[creation_token] = issue
        if self.lose_response:
            raise ServiceError(
                ErrorCode.PROVIDER_ERROR, "private provider response", may_have_applied=True
            )
        return issue

    def find_tagged_issue(self, creation_token: str) -> Issue | None:
        self.queries.append(creation_token)
        if self.lose_lookup:
            raise ServiceError(ErrorCode.PROVIDER_ERROR, "private provider response")
        return self.tokens.get(creation_token)


def _app(tracker: FakeTracker | None = None, calendar: FakeCalendar | None = None):
    tracker = tracker if tracker is not None else FakeTracker()
    calendar = calendar if calendar is not None else FakeCalendar()
    storage = FakeStorage()
    workflow = Orchestrator(
        DocumentStorageAdapter(storage),
        IssueTrackerAdapter(tracker),
        EventCalendarAdapter(calendar),
        clock=lambda: datetime(2026, 11, 24, tzinfo=UTC),
    )
    app = build_app(
        workflow,
        api_key="test-key",
        commit="test-commit",
        storage_health=storage.check_health,
        tracker_health=lambda: tracker.list_issues(limit=1),
    )
    return TestClient(app), storage, tracker, calendar


def test_authentication_and_body_limits_precede_provider_calls():
    client, storage, tracker, calendar = _app()
    for headers, content, status in [
        ({}, b"{", 401),
        ({"Authorization": "Bearer wrong"}, b"{", 401),
        (_HEADERS, b"{", 400),
        (_HEADERS, b" " * (MAX_REQUEST_BYTES + 1), 400),
        (_HEADERS, b"[]", 400),
    ]:
        assert (
            client.post("/v1/review-meetings", headers=headers, content=content).status_code
            == status
        )
    assert not any(provider.calls for provider in (storage, tracker, calendar))


def test_health_and_replay():
    client, storage, tracker, calendar = _app()
    assert client.get("/health").json() == {"status": "ok", "commit": "test-commit"}
    assert not storage.calls and not tracker.calls and not calendar.calls
    assert client.get("/health/providers").status_code == 401
    health = client.get("/health/providers", headers=_HEADERS)
    assert health.status_code == 200
    assert health.json()["providers"] == {"storage": "ok", "tracker": "ok", "calendar": "unchecked"}
    first = client.post("/v1/review-meetings", headers=_HEADERS, json=_REQUEST)
    assert first.status_code == 201
    calls = [len(provider.calls) for provider in (tracker, calendar)]
    replay = client.post("/v1/review-meetings", headers=_HEADERS, json=_REQUEST)
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["run_id"] == first.json()["run_id"]
    assert [len(provider.calls) for provider in (tracker, calendar)] == calls


def test_openapi_describes_the_authenticated_workflow():
    client, *_ = _app()
    schema = client.get("/openapi.json").json()
    post = schema["paths"]["/v1/review-meetings"]["post"]
    assert post["security"] == [{"ProductBearer": []}]
    request_schema = post["requestBody"]["content"]["application/json"]["schema"]
    assert set(request_schema["required"]) == set(_REQUEST)


@pytest.mark.parametrize("cause", ["provider_status=429", "provider_status=404", "secret-value"])
def test_refused_tracker_write_needs_operator_action_and_logs_only_safe_cause(cause, caplog):
    client, _, tracker, calendar = _app()
    tracker.failures.fail_next(
        "create_issue",
        ServiceError(
            ErrorCode.PROVIDER_ERROR,
            "private provider response",
            cause=cause,
            may_have_applied=False,
        ),
    )
    response = client.post("/v1/review-meetings", headers=_HEADERS, json=_REQUEST)
    error = response.json()["error"]
    assert response.status_code == 502
    assert error["code"] == "provider_error"
    assert error["retryable"] is False and error["may_have_applied"] is False
    assert not tracker.issues and not calendar.calls
    failure = json.loads(caplog.records[-1].getMessage())
    assert failure["provider_code"] == "PROVIDER_ERROR"
    assert failure["provider_cause"] == (cause if cause != "secret-value" else None)
    for secret in (
        "private provider response",
        "private meeting title",
        "private agenda item",
        "test-key",
        "secret-value",
    ):
        assert secret not in response.text
        assert secret not in caplog.text


def test_lost_tracker_response_adopts_card_even_if_absent_from_open_list():
    tracker = TaggedTracker()
    tracker.lose_response = True
    client, _, _, calendar = _app(tracker)
    lost = client.post("/v1/review-meetings", headers=_HEADERS, json=_REQUEST)
    assert lost.status_code == 502
    error = lost.json()["error"]
    assert error["retryable"] is True and error["may_have_applied"] is True
    assert not calendar.calls
    (token,) = tracker.tokens
    card = tracker.tokens[token]
    assert len(token) == 64 and token.startswith(lost.json()["run"]["run_id"])
    tracker.issues.clear()  # Simulate the card no longer being visible in list_issues.
    tracker.lose_lookup = True
    failed_lookup = client.post("/v1/review-meetings", headers=_HEADERS, json=_REQUEST)
    assert failed_lookup.status_code == 502
    assert failed_lookup.json()["error"]["may_have_applied"] is True
    assert failed_lookup.json()["error"]["retryable"] is True
    assert tracker.attempts == 1
    assert not calendar.calls
    tracker.lose_lookup = False
    resumed = client.post("/v1/review-meetings", headers=_HEADERS, json=_REQUEST)
    assert resumed.status_code == 201
    assert resumed.json()["issue"]["id"] == card.id
    assert tracker.queries == [token, token]
    assert tracker.attempts == 1


def test_lost_calendar_response_is_never_replayed():
    calendar = FakeCalendar()
    calendar.failures.fail_next(
        "create",
        CalendarError(CalendarCode.PROVIDER_ERROR, "private provider response", retryable=False),
        applied=True,
    )
    client, _, _, _ = _app(calendar=calendar)
    first = client.post("/v1/review-meetings", headers=_HEADERS, json=_REQUEST)
    assert first.status_code == 502
    assert first.json()["error"]["may_have_applied"] is True
    assert first.json()["error"]["retryable"] is False
    retry = client.post("/v1/review-meetings", headers=_HEADERS, json=_REQUEST)
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "outcome_unknown"
    assert calendar.operations_called() == ["create"]

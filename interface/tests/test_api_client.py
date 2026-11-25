"""HttpApiClient speaks design §1.4: Bearer key, run body, error body with the run."""

import json

import httpx2 as httpx
import pytest

from meeting_interface.api_client import ApiError, HttpApiClient
from meeting_interface.models import RunRequest, StepStatus

REQUEST = RunRequest(
    title="Sprint review",
    start="2026-11-27T15:00:00-05:00",
    end="2026-11-27T15:30:00-05:00",
    agenda=["Open bugs"],
)
RUN = {
    "run_id": "3f9a1c0d7b2e",
    "status": "completed",
    "steps": [
        {"name": "claim_run", "status": "ok"},
        {"name": "create_issue", "status": "ok"},
        {"name": "create_event", "status": "ok"},
    ],
    "issue": {"id": "6b01c2"},
    "event": {"id": "evt-81", "start": "2026-11-27T20:00:00Z", "end": "2026-11-27T20:30:00Z"},
    "agenda": {"path": "/reviews/a.md"},
    "record": {"path": "/review-runs/3f9a1c0d7b2e.json"},
}


def client_for(handler) -> HttpApiClient:
    http = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler))
    return HttpApiClient(http, api_key="key-123")


def respond(status: int, body: object, headers: dict[str, str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body, headers=headers)

    return handler


def test_posts_the_design_body_with_the_bearer_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={**RUN, "replayed": False})

    client_for(handler).run_review_meeting(REQUEST)

    assert seen[0].method == "POST"
    assert seen[0].url.path == "/v1/review-meetings"
    assert seen[0].headers["authorization"] == "Bearer key-123"
    assert json.loads(seen[0].content) == {
        "title": "Sprint review",
        "start": "2026-11-27T15:00:00-05:00",
        "end": "2026-11-27T15:30:00-05:00",
        "agenda": ["Open bugs"],
    }


def test_success_body_becomes_a_run():
    result = client_for(respond(201, {**RUN, "replayed": False})).run_review_meeting(REQUEST)

    assert result.replayed is False
    assert result.run.status == "completed"
    assert [s.name for s in result.run.steps] == ["claim_run", "create_issue", "create_event"]
    assert result.run.steps[0].status is StepStatus.OK
    assert result.run.issue_id == "6b01c2"
    assert result.run.event_id == "evt-81"
    assert result.run.event_start == "2026-11-27T20:00:00Z"
    assert result.run.agenda_path == "/reviews/a.md"


def test_replay_is_read():
    result = client_for(respond(200, {**RUN, "replayed": True})).run_review_meeting(REQUEST)

    assert result.replayed is True


def test_error_body_keeps_step_advice_and_the_run():
    body = {
        "error": {
            "code": "provider_error",
            "message": "The calendar did not confirm the event.",
            "step": "create_event",
            "retryable": False,
            "may_have_applied": True,
        },
        "run": {**RUN, "status": "partial", "event": None, "agenda": None},
    }

    with pytest.raises(ApiError) as caught:
        client_for(respond(502, body)).run_review_meeting(REQUEST)

    error = caught.value
    assert error.code == "provider_error"
    assert error.step == "create_event"
    assert error.retryable is False
    assert error.may_have_applied is True
    assert error.run is not None
    assert error.run.status == "partial"
    assert error.run.event_id is None


def test_error_before_any_step_has_no_run():
    body = {"error": {"code": "invalid_request", "message": "end must be after start"}, "run": None}

    with pytest.raises(ApiError) as caught:
        client_for(respond(400, body)).run_review_meeting(REQUEST)

    assert caught.value.run is None
    assert caught.value.retryable is False


def test_run_in_progress_reads_retry_after():
    body = {"error": {"code": "run_in_progress", "message": "busy"}, "run": None}

    with pytest.raises(ApiError) as caught:
        client_for(respond(409, body, {"Retry-After": "87"})).run_review_meeting(REQUEST)

    assert caught.value.retry_after == 87


def test_api_that_cannot_be_reached_is_api_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(ApiError) as caught:
        client_for(handler).run_review_meeting(REQUEST)

    assert caught.value.code == "api_unreachable"


@pytest.mark.parametrize(
    "body",
    [None, {"run_id": "x"}, {"error": "flat string"}],
    ids=["not-json", "run-missing-fields", "error-not-object"],
)
def test_reply_that_is_not_the_documented_shape_is_bad_response(body):
    def handler(request: httpx.Request) -> httpx.Response:
        if body is None:
            return httpx.Response(502, text="<html>Bad gateway</html>")
        return httpx.Response(200 if "run_id" in body else 500, json=body)

    with pytest.raises(ApiError) as caught:
        client_for(handler).run_review_meeting(REQUEST)

    assert caught.value.code == "bad_response"
    assert "html" not in caught.value.message.lower()


def test_unknown_step_status_is_unknown_never_ok():
    run = {**RUN, "steps": [{"name": "create_event", "status": "maybe"}]}

    result = client_for(respond(201, {**run, "replayed": False})).run_review_meeting(REQUEST)

    assert result.run.steps[0].status is StepStatus.UNKNOWN

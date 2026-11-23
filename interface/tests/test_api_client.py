"""HttpApiClient turns API responses into interface types, and every failure into ApiError."""

import json

import httpx2 as httpx
import pytest

from meeting_interface.api_client import ApiError, HttpApiClient
from meeting_interface.models import RunRequest, StepStatus

REQUEST = RunRequest(project="Team 6 sprint", meeting_date="2026-11-27", title="Sprint review")


def client_for(handler: httpx.MockTransport) -> HttpApiClient:
    return HttpApiClient(httpx.Client(base_url="https://api.test", transport=handler))


def test_success_body_becomes_run_result():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "run_id": "run-1",
                "status": "succeeded",
                "steps": [
                    {"step": "read_issues", "status": "succeeded", "detail": "4 open issues"},
                    {
                        "step": "save_agenda",
                        "status": "succeeded",
                        "detail": None,
                        "link": "https://storage.test/agenda",
                    },
                ],
            },
        )

    result = client_for(httpx.MockTransport(handler)).run_review_meeting(REQUEST)

    assert seen[0].method == "POST"
    assert seen[0].url.path == "/v1/review-meetings"
    assert json.loads(seen[0].content) == {
        "project": "Team 6 sprint",
        "meeting_date": "2026-11-27",
        "title": "Sprint review",
    }
    assert result.run_id == "run-1"
    assert [s.step for s in result.steps] == ["read_issues", "save_agenda"]
    assert result.steps[0].status is StepStatus.SUCCEEDED
    assert result.steps[1].link == "https://storage.test/agenda"


def test_error_body_becomes_api_error_with_failed_step_and_completed_steps():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "error": {
                    "code": "provider_unavailable",
                    "message": "the calendar could not be reached",
                    "step": "book_event",
                    "steps": [{"step": "read_issues", "status": "succeeded"}],
                }
            },
        )

    with pytest.raises(ApiError) as caught:
        client_for(httpx.MockTransport(handler)).run_review_meeting(REQUEST)

    error = caught.value
    assert error.code == "provider_unavailable"
    assert error.message == "the calendar could not be reached"
    assert error.step == "book_event"
    assert [s.step for s in error.steps] == ["read_issues"]


def test_api_that_cannot_be_reached_is_api_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(ApiError) as caught:
        client_for(httpx.MockTransport(handler)).run_review_meeting(REQUEST)

    assert caught.value.code == "api_unreachable"


def test_response_that_is_not_the_documented_shape_is_bad_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>Bad gateway</html>")

    with pytest.raises(ApiError) as caught:
        client_for(httpx.MockTransport(handler)).run_review_meeting(REQUEST)

    assert caught.value.code == "bad_response"
    assert "html" not in caught.value.message.lower()


def test_get_run_reads_the_run_record():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/runs/run-1"
        return httpx.Response(200, json={"run_id": "run-1", "status": "running", "steps": []})

    result = client_for(httpx.MockTransport(handler)).get_run("run-1")

    assert result.status == "running"


def test_unknown_step_status_is_uncertain_never_succeeded():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"run_id": "r", "status": "partial", "steps": [{"step": "x", "status": "maybe"}]}
        return httpx.Response(200, json=body)

    result = client_for(httpx.MockTransport(handler)).run_review_meeting(REQUEST)

    assert result.steps[0].status is StepStatus.UNCERTAIN

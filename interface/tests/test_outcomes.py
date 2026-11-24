"""When a step fails partway, the person sees what happened and what to do next."""

from meeting_interface.api_client import ApiError
from meeting_interface.fake_api import FAILED, OK, UNKNOWN, run_with
from meeting_interface.models import RunResult
from tests.conftest import FORM


def page_for(client, fake_api, error: ApiError) -> str:
    fake_api.next_error = error
    return str(client.post("/runs", data=FORM).text)


def test_partial_failure_shows_done_failed_and_not_run_separately(client, fake_api):
    page = page_for(
        client,
        fake_api,
        ApiError(
            "provider_unavailable",
            "The calendar could not be reached.",
            step="create_event",
            retryable=True,
            run=run_with(OK, OK, FAILED, status="partial", issue_id="6b01c2"),
        ),
    )

    assert 'data-step="create_issue" data-status="ok"' in page
    assert 'data-step="create_event" data-status="failed"' in page
    assert 'data-step="write_agenda" data-status="pending"' in page
    assert "Not run" in page
    assert "6b01c2" in page


def test_retryable_error_offers_try_again_with_the_same_form(client, fake_api):
    page = page_for(
        client,
        fake_api,
        ApiError("provider_unavailable", "down", step="create_event", retryable=True),
    )

    assert "Try again" in page
    assert 'hx-include="#run-form"' in page


def test_error_that_is_not_retryable_offers_no_try_again(client, fake_api):
    page = page_for(
        client,
        fake_api,
        ApiError(
            "provider_error",
            "The calendar did not confirm the event. It may have been created.",
            step="create_event",
            may_have_applied=True,
            run=run_with(OK, OK, UNKNOWN, status="partial"),
        ),
    )

    assert "Try again" not in page
    assert 'data-step="create_event" data-status="unknown"' in page
    assert "Not sure" in page


def test_run_in_progress_says_how_long_to_wait(client, fake_api):
    page = page_for(client, fake_api, ApiError("run_in_progress", "busy", retry_after=87))

    assert "about 87 seconds" in page
    assert "Try again" in page


def test_outcome_unknown_asks_for_the_team_and_shows_the_run_id(client, fake_api):
    page = page_for(
        client,
        fake_api,
        ApiError(
            "outcome_unknown",
            "An earlier attempt may have created the event.",
            step="create_event",
            run=run_with(OK, OK, UNKNOWN, status="partial"),
        ),
    )

    assert "check the calendar" in page
    assert "3f9a1c0d7b2e" in page
    assert "Try again" not in page


def test_failed_step_is_named_when_the_api_sent_no_run(client, fake_api):
    page = page_for(client, fake_api, ApiError("provider_error", "x", step="claim_run"))

    assert 'data-step="claim_run" data-status="failed"' in page


def test_run_that_is_not_completed_never_says_ready(client, fake_api):
    fake_api.next_result = RunResult(
        replayed=False, run=run_with(OK, OK, OK, UNKNOWN, status="partial")
    )

    page = client.post("/runs", data=FORM).text

    assert "ready" not in page.lower()
    assert "Not every step finished" in page

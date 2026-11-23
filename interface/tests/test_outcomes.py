"""When one vertical fails partway, the person sees what happened to each step."""

from meeting_interface.api_client import ApiError
from meeting_interface.models import RunResult, StepOutcome, StepStatus
from tests.conftest import FORM


def test_partial_failure_shows_done_failed_and_not_run_steps_separately(client, fake_api):
    fake_api.next_error = ApiError(
        "provider_unavailable",
        "the calendar could not be reached",
        step="book_event",
        steps=[
            StepOutcome("read_issues", StepStatus.SUCCEEDED, "4 open issues"),
            StepOutcome("book_event", StepStatus.FAILED),
            StepOutcome("save_agenda", StepStatus.SKIPPED),
        ],
    )

    page = client.post("/runs", data=FORM).text

    assert 'data-step="read_issues" data-status="succeeded"' in page
    assert 'data-step="book_event" data-status="failed"' in page
    assert 'data-step="save_agenda" data-status="skipped"' in page
    assert "Not run" in page
    assert "Book the review event" in page


def test_failed_step_is_named_even_when_api_lists_no_steps(client, fake_api):
    fake_api.next_error = ApiError("provider_error", "Trello refused", step="read_issues")

    page = client.post("/runs", data=FORM).text

    assert 'data-step="read_issues" data-status="failed"' in page


def test_uncertain_step_is_never_shown_as_done(client, fake_api):
    fake_api.next_result = RunResult(
        "run-3",
        "partial",
        [
            StepOutcome("read_issues", StepStatus.SUCCEEDED),
            StepOutcome("save_agenda", StepStatus.UNCERTAIN, "the write may have happened"),
        ],
    )

    page = client.post("/runs", data=FORM).text

    assert 'data-step="save_agenda" data-status="uncertain"' in page
    assert page.count("Done") == 1
    assert "Not sure" in page
    assert "the write may have happened" in page


def test_run_that_did_not_fully_succeed_never_says_ready(client, fake_api):
    fake_api.next_result = RunResult(
        "run-4", "partial", [StepOutcome("save_agenda", StepStatus.UNCERTAIN)]
    )

    page = client.post("/runs", data=FORM).text

    assert "ready" not in page.lower()
    assert "Check the steps below" in page


def test_fully_succeeded_run_says_ready(client, fake_api):
    fake_api.next_result = RunResult(
        "run-5", "succeeded", [StepOutcome("read_issues", StepStatus.SUCCEEDED)]
    )

    page = client.post("/runs", data=FORM).text

    assert "Your review meeting is ready" in page

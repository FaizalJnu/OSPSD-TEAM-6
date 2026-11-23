"""A person can run the review-meeting scenario by hand and see every step."""

from meeting_interface.api_client import ApiError
from meeting_interface.models import RunRequest, RunResult, StepOutcome, StepStatus
from tests.conftest import FORM

ALL_DONE = RunResult(
    run_id="run-1",
    status="succeeded",
    steps=[
        StepOutcome("read_issues", StepStatus.SUCCEEDED, "4 open issues"),
        StepOutcome("book_event", StepStatus.SUCCEEDED, None, "https://calendar.test/e/1"),
        StepOutcome("save_agenda", StepStatus.SUCCEEDED, None, "https://storage.test/agenda"),
        StepOutcome("link_agenda", StepStatus.SUCCEEDED),
    ],
)


def test_start_page_shows_the_scenario_form(client):
    page = client.get("/")

    assert page.status_code == 200
    for name in ("project", "meeting_date", "title"):
        assert f'name="{name}"' in page.text
    assert 'hx-post="/runs"' in page.text
    assert "/static/htmx.min.js" in page.text


def test_start_page_says_what_is_happening_while_the_run_is_slow(client):
    page = client.get("/")

    assert "htmx-indicator" in page.text
    assert "Working" in page.text


def test_htmx_is_served_locally(client):
    script = client.get("/static/htmx.min.js")

    assert script.status_code == 200
    assert "htmx" in script.text


def test_submitting_the_form_sends_exactly_what_the_person_typed(client, fake_api):
    fake_api.next_result = ALL_DONE

    client.post("/runs", data=FORM)

    assert fake_api.requests == [
        RunRequest(project="Team 6 sprint", meeting_date="2026-11-27", title="Sprint review")
    ]


def test_success_shows_every_step_in_user_terms_with_links(client, fake_api):
    fake_api.next_result = ALL_DONE

    page = client.post("/runs", data=FORM)

    assert page.status_code == 200
    for label in (
        "Read open issues",
        "Book the review event",
        "Save the agenda",
        "Link the agenda on the event and issue",
    ):
        assert label in page.text
    assert page.text.count("Done") == 4
    assert 'href="https://calendar.test/e/1"' in page.text
    assert 'href="https://storage.test/agenda"' in page.text
    assert "4 open issues" in page.text


def test_unknown_step_name_is_still_shown(client, fake_api):
    fake_api.next_result = RunResult(
        "run-2", "succeeded", [StepOutcome("notify_team", StepStatus.SUCCEEDED)]
    )

    page = client.post("/runs", data=FORM)

    assert "Notify team" in page.text


def test_error_with_no_completed_steps_still_renders(client, fake_api):
    fake_api.next_error = ApiError("invalid_request", "meeting_date must be a date")

    page = client.post("/runs", data=FORM)

    assert page.status_code == 200
    assert "meeting_date must be a date" in page.text

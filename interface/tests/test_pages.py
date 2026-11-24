"""A person can run the review-meeting scenario by hand and see every step."""

from meeting_interface.api_client import ApiError
from meeting_interface.fake_api import COMPLETED
from meeting_interface.models import RunRequest, RunResult
from tests.conftest import FORM


def test_start_page_shows_the_form(client):
    page = client.get("/")

    assert page.status_code == 200
    for name in ("title", "day", "start_time", "end_time", "time_zone", "agenda"):
        assert f'name="{name}"' in page.text
    assert 'hx-post="/runs"' in page.text
    assert '<option value="America/New_York" selected>' in page.text
    assert "/static/htmx.min.js" in page.text


def test_start_page_says_what_is_happening_while_the_run_is_slow(client):
    page = client.get("/")

    assert "htmx-indicator" in page.text
    assert "Working" in page.text


def test_htmx_is_served_locally(client):
    script = client.get("/static/htmx.min.js")

    assert script.status_code == 200
    assert "htmx" in script.text


def test_the_api_receives_the_design_body(client, fake_api):
    client.post("/runs", data=FORM)

    assert fake_api.requests == [
        RunRequest(
            title="Sprint review",
            start="2026-11-27T15:00:00-05:00",
            end="2026-11-27T15:30:00-05:00",
            agenda=["Open bugs", "Release go or no-go"],
        )
    ]


def test_completed_run_shows_every_step_and_what_was_made(client, fake_api):
    fake_api.next_result = RunResult(replayed=False, run=COMPLETED)

    page = client.post("/runs", data=FORM).text

    assert "Your review meeting is ready" in page
    for label in (
        "Start the run",
        "Open the tracker issue",
        "Book the calendar event",
        "Save the agenda",
        "Finish",
    ):
        assert label in page
    assert page.count(">Done<") == 5
    for shown in ("3f9a1c0d7b2e", "6b01c2", "evt-81", "/reviews/2026-11-27-sprint-review"):
        assert shown in page


def test_replay_says_it_was_already_prepared(client, fake_api):
    fake_api.next_result = RunResult(replayed=True, run=COMPLETED)

    page = client.post("/runs", data=FORM).text

    assert "already prepared" in page
    assert "Your review meeting is ready" not in page


def test_unreadable_form_field_is_named_and_the_api_is_not_called(client, fake_api):
    page = client.post("/runs", data={**FORM, "start_time": "soon"}).text

    assert "Enter the start time." in page
    assert fake_api.requests == []


def test_error_before_any_step_shows_its_message(client, fake_api):
    fake_api.next_error = ApiError("invalid_request", "end must be after start")

    page = client.post("/runs", data=FORM)

    assert page.status_code == 200
    assert "end must be after start" in page.text

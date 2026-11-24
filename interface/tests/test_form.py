"""The form becomes the API's body: RFC 3339 with the zone's offset, one agenda item per line."""

import pytest

from meeting_interface.form import FormProblem, MeetingForm


def form(**changes: str) -> MeetingForm:
    fields = {
        "title": "Sprint review",
        "day": "2026-11-27",
        "start_time": "15:00",
        "end_time": "15:30",
        "time_zone": "America/New_York",
        "agenda": "Open bugs\n\n  Release go or no-go  \n",
    }
    return MeetingForm(**{**fields, **changes})


def test_times_carry_the_zone_offset_in_whole_seconds():
    request = form().to_request()

    assert request.start == "2026-11-27T15:00:00-05:00"
    assert request.end == "2026-11-27T15:30:00-05:00"


def test_offset_follows_daylight_saving_on_that_day():
    assert form(day="2026-07-01").to_request().start == "2026-07-01T15:00:00-04:00"


def test_utc_and_other_zones():
    assert form(time_zone="UTC").to_request().start == "2026-11-27T15:00:00+00:00"
    assert form(time_zone="Asia/Kolkata").to_request().start == "2026-11-27T15:00:00+05:30"


def test_browser_seconds_are_dropped():
    assert form(start_time="15:00:42").to_request().start == "2026-11-27T15:00:00-05:00"


def test_agenda_is_one_trimmed_item_per_non_blank_line():
    assert form().to_request().agenda == ["Open bugs", "Release go or no-go"]


def test_title_is_sent_as_typed():
    assert form(title="  Spaces kept  ").to_request().title == "  Spaces kept  "


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"day": ""}, "date"),
        ({"start_time": "3pm"}, "start time"),
        ({"end_time": ""}, "end time"),
        ({"time_zone": "Mars/Base"}, "time zone"),
    ],
)
def test_unreadable_fields_are_named(changes, named):
    with pytest.raises(FormProblem, match=named):
        form(**changes).to_request()

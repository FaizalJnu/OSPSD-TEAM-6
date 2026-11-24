"""Step 0 (design §1.3, §2.4): the whole body is checked before any provider call."""

import pytest

from meeting_prep.orchestrator import ReviewMeetingError, validate
from tests.fake_adapters import START

BODY = {
    "title": "Storage v0.2.0 release review",
    "start": "2026-11-20T15:00:00-05:00",
    "end": "2026-11-20T15:30:00-05:00",
    "agenda": ["Open bugs"],
}


def invalid(**changes: object) -> ReviewMeetingError:
    body = {key: value for key, value in {**BODY, **changes}.items() if value is not ...}
    with pytest.raises(ReviewMeetingError) as caught:
        validate(body, START)
    assert caught.value.code == "invalid_request"
    assert caught.value.run is None
    return caught.value


def test_a_valid_body_is_trimmed_and_normalized_to_utc():
    request = validate({**BODY, "title": "  Storage v0.2.0 release review\n"}, START)

    assert request.title == "Storage v0.2.0 release review"
    assert (request.start, request.end) == ("2026-11-20T20:00:00Z", "2026-11-20T20:30:00Z")
    assert request.agenda == ("Open bugs",)


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"extra": 1}, "extra"),
        ({"title": ...}, "title"),
        ({"agenda": ...}, "agenda"),
        ({"title": "   "}, "title"),
        ({"title": "x" * 121}, "title"),
        ({"title": 7}, "title"),
        ({"start": "2026-11-20T15:00:00"}, "start"),  # no offset
        ({"start": "2026-11-20T15:00:00.5-05:00"}, "start"),  # sub-seconds
        ({"start": "2026-11-20 15:00:00Z"}, "start"),
        ({"start": "2026-02-30T15:00:00Z"}, "start"),
        ({"end": 1_700_000_000}, "end"),
        ({"end": "2026-11-20T15:00:00-05:00"}, "end"),  # equal to start
        ({"end": "2026-11-20T23:00:01-05:00"}, "8 hours"),
        ({"start": "2026-11-18T20:59:59Z", "end": "2026-11-18T21:30:00Z"}, "365 days"),  # past
        ({"start": "2027-11-19T21:00:00Z", "end": "2027-11-19T21:30:00Z"}, "365 days"),
        ({"agenda": "Open bugs"}, "agenda"),
        ({"agenda": ["x"] * 21}, "agenda"),
        ({"agenda": [""]}, "agenda item"),
        ({"agenda": ["x" * 201]}, "agenda item"),
        ({"agenda": [3]}, "agenda item"),
    ],
)
def test_an_invalid_body_is_refused_and_names_the_field(changes, field):
    assert field in invalid(**changes).message


def test_the_limits_themselves_are_allowed():
    validate(
        {
            "title": "x" * 120,
            "start": "2026-11-18T21:00:00Z",
            "end": "2026-11-19T05:00:00Z",
            "agenda": ["y" * 200] * 20,
        },
        START,
    )


def test_a_message_never_echoes_the_value():
    secret = "do-not-echo-me " * 10
    assert secret.strip() not in invalid(title=secret).message

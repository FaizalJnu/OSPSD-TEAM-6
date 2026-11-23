"""The in-memory CalendarService passes calendar-contract v0.1.0's conformance suite.

So a test that passes on the fake tells us how the real calendar behaves.
"""

import pytest
from calendar_contract import CalendarError, CreateEvent, ErrorCode
from calendar_contract.conformance import (
    CalendarServiceConformance,
    FailingServiceFactory,
    ProviderFailure,
)

from meeting_prep.fakes import FakeCalendar, failing_calendar

# How a provider failure in the conformance suite shows up from our fake.
FAILURES = {
    ProviderFailure.ACCESS_DENIED: (ErrorCode.ACCESS_DENIED, False),
    ProviderFailure.UNEXPECTED_RESPONSE: (ErrorCode.PROVIDER_ERROR, False),
    ProviderFailure.UNAVAILABLE: (ErrorCode.PROVIDER_UNAVAILABLE, True),
    ProviderFailure.UNCERTAIN_WRITE: (ErrorCode.PROVIDER_ERROR, False),
}


def calendar_failing_with(failure: ProviderFailure) -> FakeCalendar:
    # The suite checks the error each call raises, on an event that may not exist,
    # so every call fails up front. The tests below cover a write that lands before
    # its error (fail_next with applied=True).
    calendar = FakeCalendar()
    code, retryable = FAILURES[failure]
    calendar.failures.fail_always(CalendarError(code, f"fake {failure}", retryable=retryable))
    return calendar


class TestFakeCalendarConformance(CalendarServiceConformance):
    @pytest.fixture
    def service(self):
        return FakeCalendar()

    @pytest.fixture
    def failing_service(self) -> FailingServiceFactory:
        return calendar_failing_with


CREATE = CreateEvent(
    title="Review: release [3f9a1c0d7b2e]",
    start="2026-11-20T15:00:00-05:00",
    end="2026-11-20T15:30:00-05:00",
)


def test_times_are_kept_as_sent():
    event = FakeCalendar().create(CREATE)

    assert (event.start, event.end) == (CREATE.start, CREATE.end)


def test_a_lost_create_response_leaves_an_event_with_no_known_id():
    calendar = FakeCalendar()
    lost = CalendarError(ErrorCode.PROVIDER_ERROR, "timed out", retryable=False)
    calendar.failures.fail_next("create", lost, applied=True)

    with pytest.raises(CalendarError):
        calendar.create(CREATE)

    assert len(calendar.events) == 1


def test_the_failing_calendar_is_retryably_unavailable_and_creates_nothing():
    calendar = failing_calendar()

    with pytest.raises(CalendarError) as error:
        calendar.create(CREATE)

    assert error.value.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert error.value.retryable is True
    assert calendar.events == {}

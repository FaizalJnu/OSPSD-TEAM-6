"""The failure plan every fake shares."""

import pytest
from calendar_contract import CalendarError, CreateEvent, ErrorCode

from meeting_prep.fakes import FakeCalendar

CREATE = CreateEvent(title="Review", start="2030-01-07T15:00:00Z", end="2030-01-07T15:30:00Z")


def unavailable(message: str = "down") -> CalendarError:
    return CalendarError(ErrorCode.PROVIDER_UNAVAILABLE, message, retryable=True)


def test_a_queued_error_is_raised_once_then_the_fake_works_again():
    calendar = FakeCalendar()
    calendar.failures.fail_next("create", unavailable())

    with pytest.raises(CalendarError):
        calendar.create(CREATE)
    calendar.create(CREATE)

    assert calendar.operations_called() == ["create", "create"]
    assert len(calendar.events) == 1


def test_queued_errors_are_raised_in_order_and_only_for_their_operation():
    calendar = FakeCalendar()
    calendar.failures.fail_next("get", unavailable("first"))
    calendar.failures.fail_next("get", unavailable("second"))
    event = calendar.create(CREATE)

    messages = []
    for _ in range(2):
        with pytest.raises(CalendarError) as error:
            calendar.get(event.id)
        messages.append(error.value.message)

    assert messages == ["first", "second"]
    assert calendar.get(event.id) == event


def test_a_standing_error_lasts_until_cleared_and_a_queued_one_goes_first():
    calendar = FakeCalendar()
    calendar.failures.fail_always(unavailable("outage"))
    calendar.failures.fail_next("create", unavailable("queued"))

    raised = []
    for _ in range(2):
        with pytest.raises(CalendarError) as error:
            calendar.create(CREATE)
        raised.append(error.value.message)
    calendar.failures.fail_always(None)

    assert raised == ["queued", "outage"]
    assert calendar.create(CREATE).id


def test_a_standing_error_does_not_pile_up_tracebacks():
    calendar = FakeCalendar()
    calendar.failures.fail_always(unavailable())

    depths = []
    for _ in range(3):
        with pytest.raises(CalendarError) as error:
            calendar.get("x")
        depth, tb = 0, error.value.__traceback__
        while tb is not None:
            depth, tb = depth + 1, tb.tb_next
        depths.append(depth)

    assert depths[0] == depths[1] == depths[2]


def test_a_misspelled_operation_is_refused():
    with pytest.raises(ValueError, match="unknown operation 'craete'"):
        FakeCalendar().failures.fail_next("craete", unavailable())

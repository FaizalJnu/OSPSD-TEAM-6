"""Calendar writes distinguish refusal from an unknown outcome."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from calendar_contract import CalendarError, CalendarService, CreateEvent, ErrorCode, Event

from meeting_prep.adapters.base import Step, StepError


@dataclass(frozen=True)
class EventSummary:
    id: str
    title: str
    start: str
    end: str


@runtime_checkable
class _UpcomingCalendar(Protocol):
    def list_upcoming(self, start: datetime, end: datetime) -> list[Event]: ...


class EventCalendarAdapter:
    def __init__(self, calendar: CalendarService) -> None:
        self._calendar = calendar

    def create(self, title: str, start: str, end: str) -> str:
        try:
            return self._calendar.create(CreateEvent(title=title, start=start, end=end)).id
        except Exception as error:
            raise _translate(error) from None

    def upcoming(self, start: datetime, end: datetime) -> list[EventSummary]:
        if not isinstance(self._calendar, _UpcomingCalendar):
            raise StepError(
                "create_event", "provider_unavailable", retryable=False, may_have_applied=False
            )
        try:
            return [
                EventSummary(event.id, event.title, event.start, event.end)
                for event in self._calendar.list_upcoming(start, end)
            ]
        except Exception as error:
            raise _translate(error) from None


def _translate(error: Exception) -> StepError:
    step: Step = "create_event"
    if isinstance(error, TimeoutError):
        return StepError(
            step,
            "provider_error",
            retryable=False,
            may_have_applied=True,
            provider_code="TimeoutError",
        )
    if not isinstance(error, CalendarError):
        return StepError(
            step,
            "internal_error",
            retryable=False,
            may_have_applied=True,
            provider_code=type(error).__name__,
        )
    code = error.code.name
    if error.code == ErrorCode.ACCESS_DENIED:
        return StepError(
            step, "permission_denied", retryable=False, may_have_applied=False, provider_code=code
        )
    if error.code == ErrorCode.PROVIDER_UNAVAILABLE:
        return StepError(
            step,
            "provider_unavailable",
            retryable=error.retryable,
            may_have_applied=False,
            provider_code=code,
        )
    if error.code == ErrorCode.PROVIDER_ERROR:
        return StepError(
            step, "provider_error", retryable=False, may_have_applied=True, provider_code=code
        )
    return StepError(
        step, "internal_error", retryable=False, may_have_applied=False, provider_code=code
    )

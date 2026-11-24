"""In-memory ``CalendarService`` (calendar-contract v0.1.0).

It passes the contract's own conformance suite
(``tests/test_fake_calendar.py``). Event times are kept exactly as sent; the
contract tells clients to compare instants, not strings.
"""

from datetime import datetime

from calendar_contract import (
    CalendarError,
    CalendarService,
    CreateEvent,
    ErrorCode,
    Event,
    ReplaceEvent,
)

from meeting_prep.fakes._failures import FakeBase


class FakeCalendar(FakeBase, CalendarService):
    """Events in a dict keyed by ID."""

    OPERATIONS = frozenset({"create", "get", "replace", "delete", "list_upcoming"})

    def __init__(self) -> None:
        super().__init__()
        self.events: dict[str, Event] = {}
        self._created = 0

    def create(self, request: CreateEvent) -> Event:
        with self._lock:
            failure = self._start("create", request)
            self._created += 1
            event = _event(f"fake-event-{self._created}", request)
            self.events[event.id] = event
            self._finish(failure)
            return event

    def get(self, event_id: str) -> Event:
        with self._lock:
            failure = self._start("get", event_id)
            event = self._lookup(event_id)
            self._finish(failure)
            return event

    def list_upcoming(self, start: datetime, end: datetime) -> list[Event]:
        with self._lock:
            failure = self._start("list_upcoming", start, end)
            matching = [
                event
                for event in self.events.values()
                if start <= datetime.fromisoformat(event.start) < end
            ]
            self._finish(failure)
            return sorted(matching, key=lambda event: datetime.fromisoformat(event.start))

    def replace(self, event_id: str, request: ReplaceEvent) -> Event:
        with self._lock:
            failure = self._start("replace", event_id, request)
            self._lookup(event_id)
            event = _event(event_id, request)
            self.events[event_id] = event
            self._finish(failure)
            return event

    def delete(self, event_id: str) -> None:
        with self._lock:
            failure = self._start("delete", event_id)
            self._lookup(event_id)
            del self.events[event_id]
            self._finish(failure)

    def _lookup(self, event_id: str) -> Event:
        event = self.events.get(event_id)
        if event is None:
            raise CalendarError(ErrorCode.NOT_FOUND, "Event not found", retryable=False)
        return event


def failing_calendar() -> FakeCalendar:
    """A calendar that is briefly unavailable on every call (registry name ``fake-failing``).

    Staging runs with this calendar to show how a retryable failure at the calendar
    step is reported, then switches back to the real calendar and resends the same
    request, which completes the run.
    """
    calendar = FakeCalendar()
    calendar.failures.fail_always(
        CalendarError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "The calendar is currently unavailable",
            retryable=True,
        )
    )
    return calendar


def _event(event_id: str, request: CreateEvent | ReplaceEvent) -> Event:
    return Event(id=event_id, title=request.title, start=request.start, end=request.end)

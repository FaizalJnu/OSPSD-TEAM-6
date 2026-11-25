"""Turns what the person typed into the API's request body.

This is formatting, not validation: the API checks every rule (design §1.3,
step 0). The page only needs a date and times it can read, so it can add the
time zone's offset that the API requires.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from meeting_interface.models import RunRequest

TIME_ZONES = (
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "Europe/London",
    "Asia/Kolkata",
    "UTC",
)
DEFAULT_TIME_ZONE = TIME_ZONES[0]


class FormProblem(Exception):
    """A field the page cannot turn into the API's format. The message names it."""


@dataclass(frozen=True)
class MeetingForm:
    title: str
    day: str
    start_time: str
    end_time: str
    time_zone: str
    agenda: str

    def to_request(self) -> RunRequest:
        if self.time_zone not in TIME_ZONES:
            raise FormProblem("Choose a time zone from the list.")
        zone = ZoneInfo(self.time_zone)
        try:
            day = date.fromisoformat(self.day)
        except ValueError:
            raise FormProblem("Enter the meeting date.") from None
        return RunRequest(
            title=self.title,
            start=_instant(day, self.start_time, zone, "start"),
            end=_instant(day, self.end_time, zone, "end"),
            agenda=[line.strip() for line in self.agenda.splitlines() if line.strip()],
        )


def _instant(day: date, text: str, zone: ZoneInfo, name: str) -> str:
    try:
        clock = time.fromisoformat(text).replace(second=0, microsecond=0)
    except ValueError:
        raise FormProblem(f"Enter the {name} time.") from None
    # RFC 3339 with the zone's offset on that day, in whole seconds.
    return datetime.combine(day, clock, zone).isoformat(timespec="seconds")

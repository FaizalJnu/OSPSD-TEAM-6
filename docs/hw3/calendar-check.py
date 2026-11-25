"""One-off check of the Google Calendar test account. Not part of the repository.

Run from product/ with the settings loaded:

    cd product && uv run --env-file .env python ../docs/hw3/calendar-check.py

It builds the calendar through our own registry entry (team5-google, which reads
CALENDAR_TOKEN_FILE), then makes the calls the review-meeting workflow relies on:
it creates one 30-minute event tomorrow on the test account's primary calendar,
reads it back, deletes it, and checks that it is gone. It prints event IDs and
error codes only, never the token.
"""

import os
import sys
from datetime import datetime, timedelta

from calendar_contract import CalendarError, CreateEvent, ErrorCode
from meeting_prep.factories import CALENDAR_BUILDERS


def instant(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("z", "Z"))


def main() -> None:
    if not os.environ.get("CALENDAR_TOKEN_FILE"):
        sys.exit("CALENDAR_TOKEN_FILE is not set in product/.env")
    calendar = CALENDAR_BUILDERS["team5-google"](os.environ)

    start = (datetime.now().astimezone() + timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(minutes=30)
    title = "Review: calendar check  double  spaces"
    request = CreateEvent(title=title, start=start.isoformat(), end=end.isoformat())

    try:
        created = calendar.create(request)
        print("created event", created.id, "at", created.start)
        try:
            fetched = calendar.get(created.id)
            print("title kept exactly:", fetched.title == title)
            print(
                "times kept (same instants):",
                instant(fetched.start) == start and instant(fetched.end) == end,
            )
        finally:
            calendar.delete(created.id)
            print("deleted event", created.id)
        try:
            calendar.get(created.id)
            print("gone after delete: False (get still finds it)")
        except CalendarError as error:
            print("gone after delete:", error.code == ErrorCode.NOT_FOUND, f"({error.code})")
    except CalendarError as error:
        sys.exit(f"failed: {error.code} (retryable {error.retryable}): {error.message}")


if __name__ == "__main__":
    main()

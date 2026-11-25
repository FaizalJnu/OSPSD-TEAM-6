"""One-off live check of the Team 5 calendar PR branch. Not part of the repository.

Run from the Team 5 clone, whose environment has the branch's package installed:

    cd docs/hw3/OSPSD-Team-5
    uv sync --frozen --reinstall-package team5-calendar
    uv run python ../team5-pr-check.py ~/.config/team6-meeting-prep/calendar-token.json

Read-only: it never creates, changes or deletes an event. It builds the service
from in-memory Credentials (no token file), with the access token left empty so
the first call has to refresh. It then lists the next 14 days, reads one
missing event, and tries a bad refresh token. It prints counts, booleans and
error codes only, never event titles or tokens, and checks that the token file
is byte-for-byte unchanged.
"""

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from calendar_contract import CalendarError, ErrorCode
from google.oauth2.credentials import Credentials
from team5_calendar import create_calendar_service

TOKEN_URI = "https://oauth2.googleapis.com/token"


def grant_from(info: dict[str, object], refresh_token: str) -> Credentials:
    scopes = info.get("scopes")
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=str(info["client_id"]),
        client_secret=str(info["client_secret"]),
        token_uri=str(info.get("token_uri") or TOKEN_URI),
        scopes=scopes.split() if isinstance(scopes, str) else scopes,
    )


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: team5-pr-check.py <calendar-token.json>")
    path = Path(sys.argv[1]).expanduser()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    info = json.loads(path.read_text(encoding="utf-8"))

    grant = grant_from(info, str(info["refresh_token"]))
    calendar = create_calendar_service(credentials=grant)
    now = datetime.now(UTC)
    try:
        events = calendar.list_upcoming(now, now + timedelta(days=14))
    except CalendarError as error:
        sys.exit(f"list failed: {error.code} (retryable {error.retryable}): {error.message}")
    starts = [datetime.fromisoformat(event.start) for event in events]
    print("1. listed next 14 days:", len(events), "timed events")
    print("   earliest first:", starts == sorted(starts))
    print("   refreshed in memory:", grant.token is not None and grant.expiry is not None)

    try:
        calendar.get("team6prcheckmissing")
        print("2. missing event: FAILED (get returned an event)")
    except CalendarError as error:
        found = error.code == ErrorCode.NOT_FOUND
        print("2. missing event is not_found:", found, f"({error.code})")

    bad = create_calendar_service(credentials=grant_from(info, "not-a-real-refresh-token"))
    try:
        bad.list_upcoming(now, now + timedelta(days=1))
        print("3. bad refresh token: FAILED (list succeeded)")
    except CalendarError as error:
        print(
            "3. bad refresh token is provider_unavailable, not retryable:",
            error.code == ErrorCode.PROVIDER_UNAVAILABLE and not error.retryable,
        )
        print("   asks to authorize again:", "Authorize the account again" in error.message)
        print("   no secret in the error:", str(info["client_secret"]) not in str(error))

    after = hashlib.sha256(path.read_bytes()).hexdigest()
    print("4. token file unchanged:", before == after)


if __name__ == "__main__":
    main()

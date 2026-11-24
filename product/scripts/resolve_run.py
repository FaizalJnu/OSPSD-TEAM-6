"""Record an operator's answer for a run stopped at outcome_unknown (design §2.3).

A lost calendar response leaves an event that may exist with no known ID, and the
run refuses to continue until a person checks the test calendar for the run's
marker title ``[<run_id>]`` and records what they found:

    uv run --env-file .env python scripts/resolve_run.py <run_id> --event-id <id>
    uv run --env-file .env python scripts/resolve_run.py <run_id> --no-event

With --event-id, the next same request writes the agenda and finishes the run.
With --no-event, it creates the event. The script only rewrites the run record,
through the storage implementation STORAGE_PROVIDER names.
"""

import argparse
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from meeting_prep.config import ConfigError, load_settings
from meeting_prep.factories import build_implementations, build_user_storage
from meeting_prep.run_record import (
    RUN_ID_LENGTH,
    InvalidRecord,
    from_bytes,
    record_path,
    resolve_event,
    to_bytes,
)

_RUN_ID = re.compile(f"[0-9a-f]{{{RUN_ID_LENGTH}}}")
_USER_ID = re.compile("[0-9a-f]{32}")


class RecordStore(Protocol):
    def download(self, path: str) -> bytes: ...

    def replace(self, path: str, content: bytes) -> object: ...


def main(
    argv: list[str] | None = None,
    storage: RecordStore | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    parser = argparse.ArgumentParser(
        prog="resolve_run.py", description="Record the answer for an unknown calendar step."
    )
    parser.add_argument("run_id")
    parser.add_argument("--user-id", help="for a signed-in user's run in the product bucket")
    answer = parser.add_mutually_exclusive_group(required=True)
    answer.add_argument("--event-id", help="the event found in the calendar")
    answer.add_argument("--no-event", action="store_true", help="no event exists")
    args = parser.parse_args(argv)

    if not _RUN_ID.fullmatch(args.run_id):
        print(f"error: a run ID is {RUN_ID_LENGTH} lowercase hex characters", file=sys.stderr)
        return 2
    if args.user_id is not None and not _USER_ID.fullmatch(args.user_id):
        print("error: a user ID is 32 lowercase hex characters", file=sys.stderr)
        return 2
    try:
        if storage is None:
            storage = (
                build_user_storage()
                if args.user_id is not None
                else build_implementations(load_settings()).storage
            )
        path = record_path(args.run_id)
        if args.user_id is not None:
            path = f"/users/{args.user_id}{path}"
        record = from_bytes(storage.download(path), args.run_id)
        resolved = resolve_event(record, None if args.no_event else args.event_id, clock())
        storage.replace(path, to_bytes(resolved))
    except (ConfigError, InvalidRecord, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    outcome = "done" if resolved.step("create_event").state == "done" else "not_applied"
    print(f"{args.run_id}: create_event is now {outcome}. Send the same request again to finish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

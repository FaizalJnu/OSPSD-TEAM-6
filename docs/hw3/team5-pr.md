# PR for Team 5: in-memory credentials and list_upcoming

Open from `FaizalJnu:hw3/calendar-credentials-and-upcoming` into
`OSPSD-Team-5/OSPSD-Team-5` base `hw3/milestone-1`. Copy the title, then everything below
the line as the body. Fill in the live-check lines from `team5-pr-check.py` before posting.

**Title:** feat(calendar-package): accept in-memory OAuth credentials and list upcoming events

---

## Summary

`create_calendar_service` now takes either a token file (unchanged) or a user's
`google.oauth2.credentials.Credentials` held in memory. The service it returns also has
`list_upcoming(start, end)`, a read of the timed events in a window, outside the shared
contract.

Closes #64

## Why

Team 6's product acts for several signed-in users, and each user connects their own Google
Calendar. To act for user A we need a service built from user A's grant. Until now the
only way in was a token file, which meant writing each user's refresh token to disk in plain
text (details and reproduction in #64).

Our agent also needs to see a user's next meetings before it proposes one. The package
had no way to list events, so `list_upcoming` is added here as well. It is a separate method
on the package's service, so `calendar-contract` and your HTTP app are unchanged. If you'd
rather review it on its own, I can split it into a second PR.

## What changed

- [x] Added or updated functionality
- [ ] Fixed a bug
- [x] Refactored existing code
- [x] Updated documentation/tests

**Credentials** (`authorization.py`, `factory.py`)

- `create_calendar_service(*, token_file=None, credentials=None)`. Pass exactly one; both or
  neither raises `ValueError`, and a non-`Credentials` object raises `TypeError`.
- New `CredentialsAuthorization` next to `TokenAuthorization`, with the same `load()`. The
  `active_authorization` context variable is now typed with a small `Authorization`
  protocol that both satisfy, so the existing adapters need no change.
- Same rules as the token-file path: the `calendar.events` scope check, refresh under the
  per-service lock with the 10-second timeout, and the same `CalendarError` codes. The
  refresh code is moved into a shared `_refresh` helper; `TokenAuthorization` behaves
  exactly as before.
- One difference, on purpose: with credentials, a missing access token (`token=None`)
  is refreshed. A consumer usually stores only the refresh token, so the first call has to
  fetch an access token. The token-file path still requires an expired token before
  refreshing, as before.
- Refresh updates the caller's object, so the caller can read the new `token` and `expiry`
  and save them.
- When the service was built from credentials, the authorization error says to authorize
  the account again, not to run `team5_calendar.authorize` with a token file. The token-file
  message is unchanged.

**list_upcoming** (`factory.py`, `google_events.py`, `calendar_service.py`)

- `GoogleEventReader.list_events(time_min, time_max)` calls `events.list` on the primary
  calendar with `singleEvents=True`, `orderBy="startTime"`, and follows every page. It skips
  all-day and cancelled events and translates the rest with the existing `translate_event`.
- `list_upcoming(start, end)` on the factory's service checks that both are timezone-aware
  and `start < end` (else `INVALID_INPUT`, before any Google call). It then maps failures
  through the existing `_errors`, with a new `"list"` operation. A 401 gives
  `PROVIDER_UNAVAILABLE`, a 403 `ACCESS_DENIED`, a 429 or 5xx or timeout a retryable
  `PROVIDER_UNAVAILABLE`, and bad data `PROVIDER_ERROR`.
- `get_event`'s non-404 error mapping moved into `_read_failure` so both reads share it.
  `get_event` behaves exactly as before.
- `create_calendar_service` is now annotated to return `UpcomingCalendarService`, a protocol
  that extends `CalendarService` with `list_upcoming`, exported from `team5_calendar`.
  Existing `CalendarService` annotations still type-check.

**Docs:** package README (per-user credentials, upcoming events), `docs/CALENDAR_PACKAGE.md`
and the package paragraph in `AGENTS.md`.

**Compatibility:** existing `token_file` callers see no change. The only visible differences
are that calling the factory with no arguments raises `ValueError` instead of `TypeError`,
and the new export. The package version stays 0.1.0: the root `pyproject.toml` pins
`team5-calendar==0.1.0` and CI checks the `0.1.0` wheel name, so the bump belongs with your
release.

## How I tested this

- [x] Existing tests pass
- [x] Added/updated tests for new behavior
- [x] Manually verified (steps below)

New tests in `tests/test_calendar_package.py`, all offline with stubbed Google calls:

- the factory takes exactly one grant;
- two credentials-built services act only as their own user: interleaved `get`, `create` and
  `list_upcoming`, with `K_SERVICE`, `CALENDAR_MODE` and `CALENDAR_TOKEN_FILE` set to
  another account, no token file read, and nothing written;
- concurrent consumers with different credentials stay isolated;
- a refresh happens once, with the 10-second timeout, and updates the caller's `token` and
  `expiry`;
- missing scope, no refresh token, revoked refresh token and unreachable refresh each give
  `PROVIDER_UNAVAILABLE` with the right `retryable`, and no token or client secret appears
  in the error;
- the unchanged shared conformance suite on a credentials-built service;
- `list_upcoming`: the window and query arguments, skipped all-day and cancelled events,
  every page followed, bad windows rejected before calling Google, and eight provider
  failures mapped to sanitized shared errors.

Every new test fails on `hw3/milestone-1` and passes on this branch. One existing line
changed: the token-path concurrency test now asserts `isinstance(...,
TokenAuthorization)` before reading `.path`, because the context variable's type is now the
protocol.

The same steps as `checks.yml`, all passing:

```sh
uv sync --frozen --reinstall-package team5-calendar
uv build --wheel packages/team5-calendar --out-dir /tmp/calendar-wheel
uv run python scripts/check_calendar_wheel.py /tmp/calendar-wheel/team5_calendar-0.1.0-py3-none-any.whl
uv run ruff check .
uv run ruff format --check .
uv run mypy          # plus the four scripts/*.py runs from checks.yml
uv run pytest --ignore=tests/test_shared_conformance.py   # 997 passed
uv run pytest tests/test_shared_conformance.py::TestGoogleCalendarServiceConformance \
  tests/test_shared_conformance.py::TestHttpCalendarServiceConformance   # 58 passed
git diff --check
```

Live check against real Google (read-only, Team 6's test account, credentials built in memory
with no access token):

```
<paste the output of team5-pr-check.py here>
```

## Checklist

- [ ] PR is focused on one change and kept reasonably small (two related additions; happy to split)
- [x] Code builds and runs locally
- [x] No debug code, commented-out blocks, or secrets committed
- [x] Docs/README updated if behavior or setup changed

## Notes for reviewers

Student owner: Faizal Rahman (Team 6).

AI assistance (if used): an AI coding assistant helped write the code, tests and docs. I
reviewed every change and can explain each line.

Remaining work / next owner:

- Team 5: review, merge into `hw3/milestone-1`, and publish a tag (for example
  `team5-calendar-v0.2.0`) so consumers can pin it. Until then Team 6 pins this branch's commit.
- Please look closely at the refresh-token-only rule above, and at whether `list_upcoming`
  belongs in this package or later in `calendar-contract`.

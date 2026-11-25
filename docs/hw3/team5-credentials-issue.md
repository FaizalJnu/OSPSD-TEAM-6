# Issue for Team 5: per-user credentials in create_calendar_service

Post in `OSPSD-Team-5/OSPSD-Team-5` with their "Feature request" template (label `enhancement`).
Copy the title, then everything below the line as the body.

**Title:** [Feature] create_calendar_service: accept OAuth credentials in memory, not only a token file

---

## Problem

Team 6 is building a web app on your Calendar package (tag `team5-calendar-v0.1.0`). Each
signed-in user connects their own Google Calendar through OAuth, and we keep each user's tokens
encrypted in our database. To act for user A, we need to build a `CalendarService` from user A's
credentials.

`create_calendar_service` only takes a path to a token file, so the only way to hand it a user's
credentials is to write that user's refresh token to disk in plain text first. The package
already keeps two services apart: each one sets its own authorization in a context variable
for the duration of a call. So the only missing piece is how the credentials get in.

Reproduction (no network needed), against `team5-calendar-v0.1.0`:

```python
import inspect
from google.oauth2.credentials import Credentials
from calendar_contract import CalendarError
from team5_calendar import create_calendar_service

print(inspect.signature(create_calendar_service))

creds = Credentials(
    token=None,
    refresh_token="user-a-refresh-token",
    client_id="client-id.apps.googleusercontent.com",
    client_secret="client-secret",
    token_uri="https://oauth2.googleapis.com/token",
    scopes=["https://www.googleapis.com/auth/calendar.events"],
)
create_calendar_service(credentials=creds)   # TypeError

service = create_calendar_service(token_file="/nonexistent/user-a-token.json")
service.get("some-event-id")                # CalendarError
```

Output:

```
(*, token_file: str | pathlib.Path) -> calendar_contract.service.CalendarService
TypeError: create_calendar_service() got an unexpected keyword argument 'credentials'
provider_unavailable | Calendar authorization is unavailable. Run python -m team5_calendar.authorize with your OAuth client and token file.
```

The package code under `packages/team5-calendar` is the same on `hw3/milestone-1` today, so the
gap is still there.

## Proposed solution

Add an optional keyword argument, keeping `token_file` exactly as it is:

```python
def create_calendar_service(
    *,
    token_file: str | Path | None = None,
    credentials: google.oauth2.credentials.Credentials | None = None,
) -> CalendarService: ...
```

- Exactly one of the two must be given. Both or neither raises `ValueError` when the service is
  created.
- With `credentials`, the service uses that object for every call. It never reads or writes a
  file. `CALENDAR_TOKEN_FILE`, `K_SERVICE` and `CALENDAR_MODE` do not change which account it uses.
- It applies the same rules as the token-file path: the `calendar.events` scope check, refresh
  under the lock with the 10-second timeout, and the same `CalendarError` codes when the scope is
  missing, the refresh token is revoked or the refresh fails.
- `Credentials.refresh()` updates the object in place. The caller can then read `token` and
  `expiry` after a call and save them, so the next service for that user doesn't refresh again.
- When the service was built from `credentials`, the authorization error shouldn't tell the user
  to run `team5_calendar.authorize` with a token file.

A small way to do it: a second authorization class next to `TokenAuthorization` with the same
`load()` method, which holds the given `Credentials` instead of reading a path.
`_ConfiguredCalendarService` takes either one.

## Alternatives considered

- **A temporary token file per call** (mode 0600, on tmpfs, deleted afterwards). This is what we
  will do until a release has the argument. It puts a plain-text refresh token on disk for every
  call, and the service refreshes into a copy we never see, so we can't save the new access
  token and every new service refreshes again.
- **One token file per user, kept on disk.** This leaves every user's refresh token in plain
  text at rest, which our security requirements don't allow.
- **Building `_ConfiguredCalendarService` ourselves, or setting `active_authorization` directly.**
  Both are private (not in `__all__`), so any refactor on your side would break us.
- **A plain dict with the same fields as the token file instead of a `Credentials` object.** This
  works too, and we're fine with it if you prefer it. The `Credentials` object has one advantage:
  the caller can see the refreshed access token.

## Acceptance criteria

- [ ] `create_calendar_service(credentials=...)` returns a service whose `create`, `get`,
      `replace` and `delete` all use those credentials, with no file read or written.
- [ ] Two services built from different users' credentials in one process each act only as
      their own user, including when their calls are interleaved.
- [ ] An expired access token is refreshed on the passed object, and the caller can read the
      new `token` and `expiry` afterwards.
- [ ] A missing scope, a revoked refresh token and a failed refresh give the same
      `CalendarError` codes as the token-file path. No token or secret appears in any error.
- [ ] Existing `token_file` callers behave exactly as before. Passing both arguments, or
      neither, raises `ValueError`.
- [ ] Tests cover each of the above with stubbed Google calls.
- [ ] A new tag (for example `team5-calendar-v0.2.0`) so consumers can pin it.

## Additional context

- **We'll open the pull request** against `hw3/milestone-1` with the change and its tests,
  unless you'd rather make it yourselves or want it on another branch. Tell us if the shape
  above works for you.
- **Timing:** we submit our Milestone 2 on Nov 25, and launch week starts Dec 2. Until a tag
  exists, we'll pin the pull request's commit and use the temporary-file workaround. Could you
  comment here when it's tagged?
- **Out of scope:** any change to `calendar-contract` or to the HTTP service in `app/`.

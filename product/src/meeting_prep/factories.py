"""The implementation registry: one named builder per implementation we can select.

``STORAGE_PROVIDER``, ``TRACKER_PROVIDER`` and ``CALENDAR_PROVIDER`` each name an
entry below, and each builder reads only its own settings. Switching between
registered implementations is then a change to one variable and that
implementation's settings, with no code change. Adding an
implementation is a reviewed change: a pinned dependency in pyproject.toml and a
builder here.

This is the only module that names an implementation package
(tests/test_import_boundary.py). Nothing falls back to another implementation
or to a fake: an unknown name or a builder that fails stops startup.
"""

import os
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from calendar_contract import CalendarService
from cloud_storage_api import DocumentStorage
from issue_tracker_contract import IssueProvider
from storage_service.config import ConfigError as StorageConfigError
from storage_service.wiring import document_storage_from_env
from team5_calendar import create_calendar_service
from team_4_issue_tracker_trello import TrelloIssueProvider

from meeting_prep.config import ConfigError, Settings, require
from meeting_prep.fakes import (
    FakeCalendar,
    FakeStorage,
    FakeTracker,
    failing_calendar,
    failing_storage,
    failing_tracker,
)

# Team 5's Calendar call has no timeout of its own: it uses the Google client's
# default HTTP settings, which leave the timeout unset. Python gives this
# timeout to every socket opened without one. botocore, Team 4's package and the
# database driver set their own, and asyncio servers use non-blocking sockets.
DEFAULT_SOCKET_TIMEOUT_SECONDS = 30

type Builder[T] = Callable[[Mapping[str, str]], T]


def _team6_s3(env: Mapping[str, str]) -> DocumentStorage:
    """Team 6's S3-compatible storage, in-process. Settings: S3_* (see .env.example)."""
    try:
        return document_storage_from_env({**env, "STORAGE_BACKEND": "s3"})
    except StorageConfigError as error:
        # The storage service's messages name settings, never their values.
        raise ConfigError(f"STORAGE_PROVIDER=team6-s3: {error}") from None


def _team4_trello(env: Mapping[str, str]) -> IssueProvider:
    """Team 4's Trello provider. Settings: TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_LIST_ID.

    The provider takes no arguments and reads these from the process environment
    on every call (tag team-4-issue-tracker-trello-v1.0.0). Checking them here
    stops startup, instead of failing the first request.
    """
    for name in ("TRELLO_API_KEY", "TRELLO_TOKEN", "TRELLO_LIST_ID"):
        require(env, name)
    return TrelloIssueProvider()


def _team5_google(env: Mapping[str, str]) -> CalendarService:
    """Team 5's Google Calendar. Setting: CALENDAR_TOKEN_FILE, an authorized token file.

    The package authorizes on the first call and never writes the file, so the
    file can be mounted read-only.
    """
    token_file = Path(require(env, "CALENDAR_TOKEN_FILE"))
    if not token_file.is_file():
        raise ConfigError("CALENDAR_TOKEN_FILE does not name a file")
    return create_calendar_service(token_file=token_file)


STORAGE_BUILDERS: dict[str, Builder[DocumentStorage]] = {
    "team6-s3": _team6_s3,
    "fake": lambda env: FakeStorage(),
    "fake-failing": lambda env: failing_storage(),
}

TRACKER_BUILDERS: dict[str, Builder[IssueProvider]] = {
    "team4-trello": _team4_trello,
    "fake": lambda env: FakeTracker(),
    "fake-failing": lambda env: failing_tracker(),
}

CALENDAR_BUILDERS: dict[str, Builder[CalendarService]] = {
    "team5-google": _team5_google,
    "fake": lambda env: FakeCalendar(),
    "fake-failing": lambda env: failing_calendar(),
}


@dataclass(frozen=True)
class Implementations:
    """The three implementations the service uses, built once at startup."""

    storage: DocumentStorage
    tracker: IssueProvider
    calendar: CalendarService


def build_implementations(
    settings: Settings, env: Mapping[str, str] = os.environ
) -> Implementations:
    """Build the implementations ``settings`` names. Call once, at startup.

    Raises ConfigError naming the variable when a name is unknown or an
    implementation cannot be built.
    """
    socket.setdefaulttimeout(DEFAULT_SOCKET_TIMEOUT_SECONDS)
    return Implementations(
        storage=_build("STORAGE_PROVIDER", settings.storage_provider, STORAGE_BUILDERS, env),
        tracker=_build("TRACKER_PROVIDER", settings.tracker_provider, TRACKER_BUILDERS, env),
        calendar=_build("CALENDAR_PROVIDER", settings.calendar_provider, CALENDAR_BUILDERS, env),
    )


def _build[T](
    variable: str, name: str, builders: Mapping[str, Builder[T]], env: Mapping[str, str]
) -> T:
    builder = builders.get(name)
    if builder is None:
        raise ConfigError(f"{variable} must be one of: {', '.join(builders)}")
    try:
        return builder(env)
    except ConfigError:
        raise
    except Exception as error:
        # Only the type: an implementation's message could hold a setting's value.
        raise ConfigError(
            f"{variable}: the selected implementation could not be built ({type(error).__name__})"
        ) from None

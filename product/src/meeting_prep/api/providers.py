"""Resolve providers for the verified user. The demo registry stays separate.

``USER_PROVIDERS`` picks how:

* ``connections``: each user's tracker and calendar come from their own provider
  connections; documents live under their own prefix in our bucket.
* ``disconnected`` (default): documents only; tracker and calendar are unavailable.
* ``fake``: in-memory providers for tests, separate for each user.

No mode falls back to the team's test accounts (``TRELLO_TOKEN``,
``CALENDAR_TOKEN_FILE``): those belong to the fixed workflow's demo registry.
"""

import logging
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial

from meeting_prep.adapters.calendar import EventCalendarAdapter
from meeting_prep.adapters.storage import DocumentStorageAdapter
from meeting_prep.adapters.tracker import IssueTrackerAdapter
from meeting_prep.api.provider_tokens import ProviderTokenError
from meeting_prep.config import ConfigError, Settings, require
from meeting_prep.db.connection_store import Connection, ConnectionStore, Provider, Tokens
from meeting_prep.factories import build_implementations, build_user_storage, build_user_tracker
from meeting_prep.token_cipher import TokenUnreadable

logger = logging.getLogger(__name__)

MODES = ("connections", "disconnected", "fake")
# Renew a Google access token this long before it expires, so a request that
# starts with a valid token does not run out partway through.
REFRESH_MARGIN = timedelta(minutes=5)


@dataclass(frozen=True)
class UserProviders:
    storage: DocumentStorageAdapter | None = None
    tracker: IssueTrackerAdapter | None = None
    calendar: EventCalendarAdapter | None = None


def user_providers_mode(env: Mapping[str, str] = os.environ) -> str:
    mode = env.get("USER_PROVIDERS", "").strip().lower() or "disconnected"
    if mode not in MODES:
        raise ConfigError(f"USER_PROVIDERS must be one of: {', '.join(MODES)}")
    return mode


def build_user_providers(
    env: Mapping[str, str] = os.environ,
    connections: ConnectionStore | None = None,
) -> Callable[[str], UserProviders]:
    mode = user_providers_mode(env)
    if mode == "fake":
        return _fake_providers()
    user_storage = _user_storage(env)
    if mode == "disconnected":
        return partial(_storage_only, user_storage)
    if connections is None:
        raise ConfigError("USER_PROVIDERS=connections needs DATABASE_URL and CONNECTION_TOKEN_KEY")
    return ConnectionResolver(
        connections,
        user_storage,
        trello_app_key=require(env, "TRELLO_APP_KEY"),
    ).for_user


class ConnectionResolver:
    """Builds one signed-in user's providers from that user's own connections.

    A provider is None when the user has not connected it, it needs attention
    (revoked or expired), or its tokens cannot be read; the API then tells the
    user what to connect. Nothing falls back to another account.
    """

    def __init__(
        self,
        connections: ConnectionStore,
        storage: DocumentStorageAdapter | None,
        *,
        trello_app_key: str,
        tracker_for: Callable[[str, str, str], IssueTrackerAdapter] | None = None,
        calendar_for: Callable[[Connection], EventCalendarAdapter] | None = None,
        renew_google: Callable[[Connection], Tokens] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connections = connections
        self._storage = storage
        self._trello_app_key = trello_app_key
        self._tracker_for = tracker_for or _trello_tracker
        # Calendar connections need Team 5's credentials argument; until that
        # package is pinned, the calendar stays unavailable.
        self._calendar_for = calendar_for
        self._renew_google = renew_google
        self._clock = clock or (lambda: datetime.now(UTC))

    def for_user(self, user_id: str) -> UserProviders:
        now = self._clock()
        return UserProviders(
            storage=self._storage,
            tracker=self._tracker(user_id, now),
            calendar=self._calendar(user_id, now),
        )

    def _tracker(self, user_id: str, now: datetime) -> IssueTrackerAdapter | None:
        trello = self._read(user_id, "trello")
        if trello is None or trello.status != "connected":
            return None
        if trello.expired(now):
            # Trello tokens do not renew: the user authorizes again.
            self._connections.mark_needs_attention(user_id, "trello", now)
            return None
        list_id = trello.settings.get("list_id")
        if not list_id:
            return None
        return self._tracker_for(self._trello_app_key, trello.access_token, list_id)

    def _calendar(self, user_id: str, now: datetime) -> EventCalendarAdapter | None:
        if self._calendar_for is None:
            return None
        google = self._read(user_id, "google_calendar")
        if google is None or google.status != "connected":
            return None
        if google.expired(now, REFRESH_MARGIN) and self._renew_google is not None:
            try:
                renewed = self._connections.refresh(
                    user_id, "google_calendar", now, self._renew_google, margin=REFRESH_MARGIN
                )
            except ProviderTokenError:
                # Google is unreachable. Keep the stored token: the provider call
                # fails with provider_unavailable, and the next request retries.
                renewed = google
            if renewed is None or renewed.status != "connected":
                return None
            google = renewed
        return self._calendar_for(google)

    def _read(self, user_id: str, provider: Provider) -> Connection | None:
        try:
            return self._connections.get(user_id, provider)
        except TokenUnreadable:
            # Wrong or rotated-out key, or a changed row. Not the user's doing, so the
            # connection is not marked; the operator fixes CONNECTION_TOKEN_KEY.
            logger.error("provider connection unreadable", extra={"provider": provider})
            return None


def _trello_tracker(api_key: str, token: str, list_id: str) -> IssueTrackerAdapter:
    return IssueTrackerAdapter(build_user_tracker(api_key, token, list_id))


def _user_storage(env: Mapping[str, str]) -> DocumentStorageAdapter | None:
    name = env.get("USER_STORAGE_PROVIDER", "").strip()
    if name and name != "team6-s3":
        raise ConfigError("USER_STORAGE_PROVIDER must be team6-s3 or unset")
    return DocumentStorageAdapter(build_user_storage(env)) if name else None


def _fake_providers() -> Callable[[str], UserProviders]:
    # Test accounts share a bucket, to exercise real prefix isolation. Tracker
    # and calendar hold separate data for each account.
    fake_settings = Settings("fake", "fake", "fake", "")
    storage = DocumentStorageAdapter(build_implementations(fake_settings).storage)
    per_user: dict[str, UserProviders] = {}
    lock = threading.Lock()

    def for_user(user_id: str) -> UserProviders:
        with lock:
            if user_id not in per_user:
                own = build_implementations(fake_settings)
                per_user[user_id] = UserProviders(
                    storage,
                    IssueTrackerAdapter(own.tracker),
                    EventCalendarAdapter(own.calendar),
                )
            return per_user[user_id]

    return for_user


def _storage_only(storage: DocumentStorageAdapter | None, _user_id: str) -> UserProviders:
    return UserProviders(storage=storage)

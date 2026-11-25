"""Resolve providers for the verified user. The demo registry stays separate."""

import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial

from meeting_prep.adapters.calendar import EventCalendarAdapter
from meeting_prep.adapters.storage import DocumentStorageAdapter
from meeting_prep.adapters.tracker import IssueTrackerAdapter
from meeting_prep.config import ConfigError, Settings
from meeting_prep.factories import build_implementations, build_user_storage


@dataclass(frozen=True)
class UserProviders:
    storage: DocumentStorageAdapter | None = None
    tracker: IssueTrackerAdapter | None = None
    calendar: EventCalendarAdapter | None = None


def build_user_providers(
    env: Mapping[str, str] = os.environ,
) -> Callable[[str], UserProviders]:
    mode = env.get("USER_PROVIDERS", "").strip() or "disconnected"
    if mode == "fake":
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
    if mode != "disconnected":
        raise ConfigError("USER_PROVIDERS must be disconnected or fake")
    # Faizal's explicit connection resolver can replace this function. The shared
    # demo's tracker and calendar credentials cannot be used for a signed-in user.
    name = env.get("USER_STORAGE_PROVIDER", "").strip()
    if name and name != "team6-s3":
        raise ConfigError("USER_STORAGE_PROVIDER must be team6-s3 or unset")
    user_storage = DocumentStorageAdapter(build_user_storage(env)) if name else None
    return partial(_storage_only, user_storage)


def _storage_only(storage: DocumentStorageAdapter | None, _user_id: str) -> UserProviders:
    return UserProviders(storage=storage)

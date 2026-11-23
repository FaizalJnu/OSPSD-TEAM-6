"""Settings read once at startup from environment variables.

``.env.example`` lists every variable and what it does. A missing or invalid
setting raises ``ConfigError`` before the service serves anything. The message
names the variable, never its value, so a startup log line cannot leak a
credential.

This module reads the settings every service shares. The implementation
registry (``factories.py``) checks that the three provider names are known, and
each registry entry reads its own settings, such as ``S3_BUCKET``.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field


class ConfigError(Exception):
    """A required setting is missing or invalid. Raised at startup."""


@dataclass(frozen=True)
class Settings:
    storage_provider: str
    tracker_provider: str
    calendar_provider: str
    # A database URL can hold a password, so it stays out of repr and tracebacks.
    database_url: str = field(repr=False)


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    return Settings(
        storage_provider=provider_name(env, "STORAGE_PROVIDER"),
        tracker_provider=provider_name(env, "TRACKER_PROVIDER"),
        calendar_provider=provider_name(env, "CALENDAR_PROVIDER"),
        database_url=require(env, "DATABASE_URL"),
    )


def require(env: Mapping[str, str], name: str) -> str:
    """Return the setting ``name`` with surrounding spaces removed, or raise ConfigError."""
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


def provider_name(env: Mapping[str, str], name: str) -> str:
    """Return a registry name such as ``team5-google``, compared without regard to case."""
    return require(env, name).lower()

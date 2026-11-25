"""Settings, read from environment variables."""

import os
from dataclasses import dataclass, field


class ConfigError(Exception):
    """A required setting is missing. The message names it, never a value."""


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    agent_base_url: str
    session_cookie: str
    public_origin: str | None
    fake_api: bool
    api_timeout_seconds: float
    # The API key stays out of repr, so it cannot reach a log line or traceback.
    api_key: str = field(repr=False)


def load_settings() -> Settings:
    fake_api = os.environ.get("FAKE_API", "") == "1"
    api_key = os.environ.get("PRODUCT_API_KEY", "").strip()
    if not fake_api and not api_key:
        raise ConfigError("PRODUCT_API_KEY is not set")
    return Settings(
        api_base_url=os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"),
        agent_base_url=os.environ.get("AGENT_BASE_URL", "http://127.0.0.1:8001"),
        # The API's cookie: __Host-meeting_session over HTTPS, meeting_session on loopback.
        session_cookie=os.environ.get("SESSION_COOKIE", "__Host-meeting_session"),
        # Must equal the API's PUBLIC_ORIGIN: the origin the browser uses for both.
        public_origin=os.environ.get("PUBLIC_ORIGIN") or None,
        fake_api=fake_api,
        # One run makes several provider calls in a row (design §2.2), so wait long enough.
        api_timeout_seconds=float(os.environ.get("API_TIMEOUT_SECONDS", "180")),
        api_key=api_key,
    )

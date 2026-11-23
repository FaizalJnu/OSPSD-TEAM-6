"""Settings, read from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    fake_api: bool
    api_timeout_seconds: float


def load_settings() -> Settings:
    return Settings(
        api_base_url=os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"),
        fake_api=os.environ.get("FAKE_API", "") == "1",
        api_timeout_seconds=float(os.environ.get("API_TIMEOUT_SECONDS", "60")),
    )

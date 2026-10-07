"""Settings, read once at startup from environment variables.

See ``.env.example`` for every variable and what it does.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

BACKENDS = ("s3", "memory")
DEFAULT_MAX_UPLOAD_BYTES = 1024**3  # 1 GiB


class ConfigError(Exception):
    """A required setting is missing or invalid. Raised at startup."""


@dataclass(frozen=True)
class S3Settings:
    endpoint: str
    region: str
    bucket: str
    access_key: str
    secret_key: str = field(repr=False)  # keeps the secret out of logs and tracebacks


@dataclass(frozen=True)
class Settings:
    backend: str
    max_upload_bytes: int
    s3: S3Settings | None  # only set when backend == "s3"


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    backend = env.get("STORAGE_BACKEND", "").strip().lower()
    if backend not in BACKENDS:
        raise ConfigError(f"STORAGE_BACKEND must be one of {BACKENDS}, got {backend!r}")
    return Settings(
        backend=backend,
        max_upload_bytes=_positive_int(env, "MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES),
        s3=_load_s3_settings(env) if backend == "s3" else None,
    )


def _load_s3_settings(env: Mapping[str, str]) -> S3Settings:
    required = ("S3_ENDPOINT", "S3_REGION", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY")
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise ConfigError(f"the s3 backend needs these settings: {', '.join(missing)}")
    return S3Settings(
        endpoint=env["S3_ENDPOINT"],
        region=env["S3_REGION"],
        bucket=env["S3_BUCKET"],
        access_key=env["S3_ACCESS_KEY"],
        secret_key=env["S3_SECRET_KEY"],
    )


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "")
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}") from None
    if value <= 0:
        raise ConfigError(f"{name} must be positive, got {value}")
    return value

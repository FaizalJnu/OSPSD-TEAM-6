"""Turning ``DATABASE_URL`` into a SQLAlchemy engine for SQLite or Postgres."""

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from meeting_prep.config import ConfigError

# Neon and most hosts hand out postgresql:// or postgres:// URLs. Both mean
# psycopg 3 here, the only Postgres driver installed.
_POSTGRES_NAMES = ("postgres", "postgresql", "postgresql+psycopg")
_SQLITE_NAMES = ("sqlite", "sqlite+pysqlite")


def database_url(raw: str) -> URL:
    """Parse a SQLite or Postgres URL. Errors name DATABASE_URL, never the URL itself."""
    try:
        url = make_url(raw)
    except ArgumentError:
        raise ConfigError("DATABASE_URL is not a database URL") from None
    if url.drivername in _POSTGRES_NAMES:
        return url.set(drivername="postgresql+psycopg")
    if url.drivername in _SQLITE_NAMES:
        return url
    raise ConfigError("DATABASE_URL must start with sqlite://, postgresql:// or postgres://")


def create_engine_for(raw_url: str) -> Engine:
    """An engine for ``raw_url``. Create one per process and share it."""
    url = database_url(raw_url)
    if url.get_backend_name() == "sqlite":
        engine = create_engine(url)
        event.listen(engine, "connect", _enforce_sqlite_foreign_keys)
        return engine
    return create_engine(
        url,
        # Neon suspends an idle database and drops its connections. Test each
        # connection before use, and replace connections older than 5 minutes.
        pool_pre_ping=True,
        pool_recycle=300,
        # Free tiers allow few connections; every service process holds up to 10.
        pool_size=5,
        max_overflow=5,
        # psycopg prepares statements it runs often. Neon's pooled endpoint
        # (PgBouncer in transaction mode) can hand the next statement to a
        # different server connection, where that prepared statement is missing.
        connect_args={"prepare_threshold": None},
    )


def _enforce_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    # SQLite ignores foreign keys unless each connection turns them on, and
    # Postgres always enforces them. Tests on SQLite then catch the same mistakes.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

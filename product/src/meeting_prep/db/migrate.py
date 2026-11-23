"""Running Alembic migrations from code, for deploys and tests."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from meeting_prep.db.engine import create_engine_for

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def alembic_config(url: str) -> Config:
    """An Alembic configuration for ``url`` that needs no alembic.ini."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Passed as an attribute, not an option: options go through configparser,
    # which would treat a "%" in a URL-encoded password as interpolation.
    config.attributes["database_url"] = url
    return config


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)


def current_revision(url: str) -> str | None:
    """The revision the database at ``url`` is at, or None before the first migration."""
    engine = create_engine_for(url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def head_revisions() -> tuple[str, ...]:
    """The newest revisions. There must be exactly one; two means two branches to merge."""
    script = ScriptDirectory.from_config(alembic_config("sqlite://"))
    return tuple(script.get_heads())

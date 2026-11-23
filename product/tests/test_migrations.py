"""Migrations run on SQLite and on Postgres, and match the tables in code.

The SQLite cases run in the fast suite. The Postgres cases are marked
``postgres`` and need TEST_DATABASE_URL; CI runs them against a Postgres
container. Each Postgres case works in a schema of its own and drops it
afterwards, so any database you can create schemas in will do.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from meeting_prep.config import ConfigError
from meeting_prep.db import (
    create_engine_for,
    current_revision,
    database_url,
    downgrade,
    head_revisions,
    load_tables,
    upgrade,
)
from meeting_prep.db.__main__ import main as db_cli


@pytest.fixture
def sqlite_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'meetings.sqlite3'}"


@pytest.fixture
def postgres_url() -> Iterator[str]:
    base = os.environ.get("TEST_DATABASE_URL", "")
    if not base:
        pytest.fail("set TEST_DATABASE_URL to a Postgres database to run the postgres tests")
    schema = f"test_{uuid.uuid4().hex[:12]}"
    admin = create_engine_for(base)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    # Every connection made from this URL works in the new schema.
    url = database_url(base).update_query_dict({"options": f"-csearch_path={schema}"})
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def url(request) -> str:
    fixture_name: str = f"{request.param}_url"
    value: str = request.getfixturevalue(fixture_name)
    return value


def test_there_is_exactly_one_head():
    # Two heads mean two pull requests each added a migration after the same parent.
    # The second to merge sets its down_revision to the first one's revision.
    assert len(head_revisions()) == 1


def test_upgrade_to_head_then_downgrade_to_base(url):
    assert current_revision(url) is None

    upgrade(url)
    assert current_revision(url) == head_revisions()[0]

    downgrade(url, "base")
    assert current_revision(url) is None


def test_upgrade_twice_changes_nothing(url):
    upgrade(url)
    upgrade(url)

    assert current_revision(url) == head_revisions()[0]


def test_the_migrated_schema_matches_the_tables_in_code(url):
    # A table or column defined in meeting_prep/db/tables/ without a migration,
    # or a migration that differs from the code, shows up here.
    upgrade(url)
    engine = create_engine_for(url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            differences = compare_metadata(context, load_tables())
            tables = set(inspect(connection).get_table_names())
    finally:
        engine.dispose()

    assert differences == []
    assert "alembic_version" in tables


@pytest.mark.parametrize(
    ("raw", "drivername"),
    [
        ("postgresql://u:p@db.example.com/meetings?sslmode=require", "postgresql+psycopg"),
        ("postgres://u:p@db.example.com/meetings", "postgresql+psycopg"),
        ("postgresql+psycopg://u:p@db.example.com/meetings", "postgresql+psycopg"),
        ("sqlite:///dev.sqlite3", "sqlite"),
        ("sqlite://", "sqlite"),
    ],
)
def test_database_urls_use_the_installed_drivers(raw, drivername):
    assert database_url(raw).drivername == drivername


@pytest.mark.parametrize(
    "raw",
    ["not a url", "mysql://u:s3cret@db.example.com/x", "postgresql+psycopg2://u:s3cret@h/x"],
)
def test_other_database_urls_are_refused_without_echoing_them(raw):
    with pytest.raises(ConfigError, match="^DATABASE_URL ") as error:
        database_url(raw)

    assert "s3cret" not in str(error.value)


def test_sqlite_enforces_foreign_keys(sqlite_url):
    engine = create_engine_for(sqlite_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
    finally:
        engine.dispose()


def test_the_command_line_upgrades_the_database_in_database_url(sqlite_url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", sqlite_url)

    assert db_cli(["upgrade"]) == 0
    assert capsys.readouterr().out.strip() == head_revisions()[0]


def test_the_command_line_needs_database_url(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert db_cli(["current"]) == 2
    assert capsys.readouterr().err.strip() == "error: DATABASE_URL is not set"

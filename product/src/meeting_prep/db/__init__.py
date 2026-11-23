"""Database access: the engine, the shared table base, and migrations.

* ``create_engine_for(url)`` builds an engine for a SQLite or Postgres
  ``DATABASE_URL``. Create one per process.
* ``Base`` is the declarative base every table uses. Tables live in
  ``meeting_prep/db/tables/``, one module per owning area.
* Schema changes go through Alembic migrations in ``migrations/versions/``.
  ``python -m meeting_prep.db upgrade`` applies them.

Only this package imports SQLAlchemy, Alembic or a database driver
(tests/test_import_boundary.py), so every query lives here and stays
parameterized.
"""

from meeting_prep.db.base import Base, load_tables
from meeting_prep.db.engine import create_engine_for, database_url
from meeting_prep.db.migrate import current_revision, downgrade, head_revisions, upgrade

__all__ = [
    "Base",
    "create_engine_for",
    "current_revision",
    "database_url",
    "downgrade",
    "head_revisions",
    "load_tables",
    "upgrade",
]

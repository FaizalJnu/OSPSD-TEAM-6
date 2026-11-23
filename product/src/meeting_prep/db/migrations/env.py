"""Alembic's entry point. Alembic runs this for every migration command.

The database URL comes from ``meeting_prep.db.migrate.alembic_config`` when
code runs the migrations, or from DATABASE_URL for the ``alembic`` command line.
"""

import os

from alembic import context

from meeting_prep.config import require
from meeting_prep.db.base import load_tables
from meeting_prep.db.engine import create_engine_for, database_url

config = context.config
url: str = config.attributes.get("database_url") or require(os.environ, "DATABASE_URL")
target_metadata = load_tables()

# Every migration must run on SQLite (development, tests) and Postgres (deployed).
# render_as_batch makes autogenerate write batch operations, which rewrite a SQLite
# table to change it, since SQLite's ALTER TABLE is limited. On Postgres the same
# migration emits ordinary ALTER statements.
if context.is_offline_mode():
    context.configure(
        url=database_url(url),
        literal_binds=True,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine_for(url)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()

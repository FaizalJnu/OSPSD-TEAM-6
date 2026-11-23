"""The base class and metadata every table shares."""

import importlib
import pkgutil

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Every constraint and index gets a predictable name. Alembic needs names to
# change or drop a constraint later, and SQLite generates none of its own.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Subclass this for ORM tables, or pass ``Base.metadata`` to a Core ``Table``."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def load_tables() -> MetaData:
    """Import every module in ``meeting_prep.db.tables`` and return the full metadata.

    Alembic and the schema test call this, so a new table module is picked up
    without being listed anywhere.
    """
    from meeting_prep.db import tables

    for module in pkgutil.iter_modules(tables.__path__):
        importlib.import_module(f"{tables.__name__}.{module.name}")
    return Base.metadata

"""Alembic environment.

URL resolution order:
1. ``config.attributes["url"]`` (tests pass a disposable database here),
2. ``-x url=...`` on the command line,
3. the application settings (``WFIQ_DB_BACKEND`` / ``WFIQ_SQLITE_PATH`` / ``WFIQ_DB_*``).
"""

from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy.engine import URL, make_url

from app.core.config import get_settings
from app.core.database import create_db_engine
from app.db.registry import metadata
from app.db.types import DecimalType, UTCDateTime

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)


def _url() -> URL:
    if "url" in config.attributes:
        return make_url(config.attributes["url"])
    x_args = context.get_x_argument(as_dictionary=True)
    if "url" in x_args:
        return make_url(x_args["url"])
    return get_settings().database_url()


def render_item(type_: str, obj: object, autogen_context: AutogenContext) -> str | bool:
    """Write portable app types into migrations as plain SQLAlchemy types (self-contained)."""
    if type_ == "type" and isinstance(obj, DecimalType):
        return f"sa.Numeric(precision={obj.precision}, scale={obj.scale})"
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


COMMON: dict[str, Any] = {
    "target_metadata": metadata,
    "render_as_batch": True,  # SQLite needs table rebuilds for most ALTERs
    "compare_type": True,
    "compare_server_default": False,
    "render_item": render_item,
}


def run_migrations_offline() -> None:
    url = _url()
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"}, **COMMON)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_db_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, **COMMON)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

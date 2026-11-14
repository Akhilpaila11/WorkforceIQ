"""Database engine, session factory and transaction scope.

Beginner note
-------------
* The **engine** manages connections to the database file/server.
* A **session** is one unit of work: changes are collected and written in a single
  transaction when ``commit()`` is called; on any error everything is rolled back.

SQLite needs two connection settings to behave like a "real" relational database:
``PRAGMA foreign_keys = ON`` (otherwise foreign keys are ignored!) and a busy timeout.

Connectivity check (PowerShell, from ``backend/``)::

    .\\.venv\\Scripts\\python.exe -m app.core.database
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.guards import install_immutability_guard


def _enable_sqlite_integrity(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA busy_timeout = 5000")
    cursor.close()


def create_db_engine(url: URL | str, *, echo: bool = False) -> Engine:
    """Create an engine; for SQLite, ensure the folder exists and foreign keys are enforced."""
    url = make_url(url)
    if url.get_backend_name() == "sqlite":
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, echo=echo)
        event.listen(engine, "connect", _enable_sqlite_integrity)
        return engine
    return create_engine(url, echo=echo, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: objects stay readable after commit (handy for API responses).
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)
    return install_immutability_guard(factory)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit on success, roll back on any exception, always close."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection(engine: Engine) -> dict[str, str]:
    """Run a trivial query and report what we are connected to."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        if engine.dialect.name == "sqlite":
            version = conn.execute(text("SELECT sqlite_version()")).scalar_one()
            fk = conn.execute(text("PRAGMA foreign_keys")).scalar_one()
            return {
                "dialect": "sqlite",
                "version": str(version),
                "database": str(engine.url.database),
                "foreign_keys": "ON" if fk == 1 else "OFF",
            }
        version = conn.execute(text("SELECT version()")).scalar_one()
        return {
            "dialect": engine.dialect.name,
            "version": str(version),
            "database": str(engine.url.database),
        }


def main() -> int:
    settings = get_settings()
    url = settings.database_url()
    print(f"Connecting to {url.render_as_string(hide_password=True)}")
    try:
        info = check_connection(create_db_engine(url))
    except Exception as exc:  # report any driver error clearly, then fail
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1
    for key, value in info.items():
        print(f"  {key}: {value}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

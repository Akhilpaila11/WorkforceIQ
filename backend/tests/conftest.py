"""Shared pytest fixtures.

Database tests never touch the developer database: a template SQLite file is migrated once
per test session with Alembic, and every test gets its own copy of it.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.database import create_db_engine, make_session_factory

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every WFIQ_* variable so tests do not depend on the developer's machine."""
    for name in list(os.environ):
        if name.startswith("WFIQ_"):
            monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def backend_dir() -> Path:
    return BACKEND_DIR


def sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("template") / "template.sqlite3"
    command.upgrade(alembic_config(sqlite_url(path)), "head")
    return path


@pytest.fixture
def engine(migrated_template: Path, tmp_path: Path) -> Iterator[Engine]:
    db_file = tmp_path / "test.sqlite3"
    shutil.copyfile(migrated_template, db_file)
    eng = create_db_engine(sqlite_url(db_file))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    factory = make_session_factory(engine)
    with factory() as s:
        yield s
        s.rollback()

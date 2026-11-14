"""Load a generated dataset into the application database (SQLite by default).

Safe regeneration: the target database is migrated to Alembic head, then - in ONE
transaction - the dataset tables and derived analysis tables are emptied and refilled in
foreign-key order. The database file is never deleted, ``audit_event`` (append-only) is never
touched, and ground truth is never loaded.
"""

from __future__ import annotations

from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.engine import URL

from app.core.config import BACKEND_DIR
from app.core.database import create_db_engine
from app.db.registry import metadata

Row = dict[str, Any]
ANALYSIS_TABLES = (
    "recommendation_gap_link",
    "recommendation",
    "gap_analysis",
    "capacity_snapshot",
    "forecast_result",
    "exception_finding",
    "analysis_run",
)
BATCH = 5000


def migrate(url: URL | str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["url"] = str(url) if isinstance(url, str) else url.render_as_string(False)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def load_dataset(tables: dict[str, list[Row]], url: URL | str) -> dict[str, int]:
    migrate(url)
    managed = set(tables) | set(ANALYSIS_TABLES)
    engine = create_db_engine(url)
    try:
        with engine.begin() as conn:
            for table in reversed(metadata.sorted_tables):
                if table.name in managed:
                    conn.execute(table.delete())
            for table in metadata.sorted_tables:
                rows = tables.get(table.name) or []
                for start in range(0, len(rows), BATCH):
                    conn.execute(table.insert(), rows[start : start + BATCH])
            counts = {
                t: int(conn.scalar(select(func.count()).select_from(metadata.tables[t])) or 0)
                for t in sorted(tables)
            }
    finally:
        engine.dispose()
    mismatch = {t: (counts[t], len(rows)) for t, rows in tables.items() if counts[t] != len(rows)}
    if mismatch:
        raise RuntimeError(f"row counts after load differ: {mismatch}")
    return counts

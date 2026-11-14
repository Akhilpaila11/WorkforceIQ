"""SQL aggregates for the dashboard summary (COUNT / SUM / MIN / MAX over whole tables)."""

from __future__ import annotations

from datetime import date
from enum import Enum

from sqlalchemy import Table, func, select
from sqlalchemy.orm import Session

from app.db.models import DatasetMetadata
from app.db.registry import metadata


class SqlStatsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _table(name: str) -> Table:
        return metadata.tables[name]

    def count(
        self, table: str, *, where_null: str | None = None, where_true: str | None = None
    ) -> int:
        t = self._table(table)
        query = select(func.count()).select_from(t)
        if where_null is not None:
            query = query.where(t.c[where_null].is_(None))
        if where_true is not None:
            query = query.where(t.c[where_true].is_(True))
        return int(self._session.scalar(query) or 0)

    def count_by(self, table: str, column: str) -> dict[str, int]:
        col = self._table(table).c[column]
        rows = self._session.execute(select(col, func.count()).group_by(col).order_by(col))
        return {(k.value if isinstance(k, Enum) else str(k)): int(n) for k, n in rows}

    def total(self, table: str, column: str) -> float:
        return float(self._session.scalar(select(func.sum(self._table(table).c[column]))) or 0)

    def date_range(self, table: str, column: str) -> tuple[date | None, date | None]:
        col = self._table(table).c[column]
        low, high = self._session.execute(select(func.min(col), func.max(col))).one()
        return low, high

    def dataset_metadata(self) -> dict[str, str]:
        rows = self._session.scalars(select(DatasetMetadata).order_by(DatasetMetadata.key))
        return {r.key: r.value for r in rows}

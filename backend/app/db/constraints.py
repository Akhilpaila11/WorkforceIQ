"""Reusable, dialect-portable CHECK constraints (valid SQL on SQLite and PostgreSQL)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint

from app.domain.ids import ID_FORMATS, EntityKind


def id_format_check(column: str, kind: EntityKind) -> CheckConstraint:
    """Prefix + exact length. Full digit-level validation is done in Python (domain.ids)."""
    fmt = ID_FORMATS[kind]
    return CheckConstraint(
        f"{column} LIKE '{fmt.prefix}-%' AND length({column}) = {fmt.length}",
        name=f"{column}_format",
    )


def date_order_check(start: str, end: str, name: str = "date_order") -> CheckConstraint:
    """``end`` is optional (open-ended) or not before ``start``."""
    return CheckConstraint(f"{end} IS NULL OR {end} >= {start}", name=name)


def between_check(column: str, low: float | int, high: float | int) -> CheckConstraint:
    return CheckConstraint(f"{column} >= {low} AND {column} <= {high}", name=f"{column}_range")


def proficiency_check(column: str) -> CheckConstraint:
    return between_check(column, 1, 5)

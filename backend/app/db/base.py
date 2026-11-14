"""Declarative base for every ORM model.

The naming convention gives every constraint a predictable name (``pk_employee``,
``fk_employee_role_id_role``, ``ck_employee_dates`` ...). Predictable names make Alembic
migrations reproducible and error messages readable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import MetaData, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import UTCDateTime

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    #: Columns (besides the primary key) that may never change after insert.
    #: Enforced by app.db.guards (ORM) - see BR-VAL-007.
    __immutable__: ClassVar[tuple[str, ...]] = ()


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    """``created_at`` / ``updated_at`` audit columns (UTC)."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="When the row was inserted (UTC).",
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="When the row was last modified (UTC).",
    )

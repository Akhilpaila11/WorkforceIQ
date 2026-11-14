"""Portable column types that behave identically on SQLite and PostgreSQL.

* :class:`DecimalType` - exact ``Decimal`` values (``NUMERIC(p, s)``). SQLite has no native
  decimal type, so values are stored as numbers and re-quantised on read; PostgreSQL stores
  them natively.
* :class:`UTCDateTime` - always timezone-aware UTC in Python. SQLite stores naive UTC text.
* :data:`JSONType` - ``JSONB`` on PostgreSQL, JSON text on SQLite.
* :func:`enum_type` - ``VARCHAR`` + ``CHECK (col IN (...))``; no native DB enum, so new values
  are a simple migration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Dialect, Enum, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator, TypeEngine

from app.domain.units import to_decimal


class DecimalType(TypeDecorator[Decimal]):
    impl = Numeric
    cache_ok = True

    def __init__(self, precision: int, scale: int) -> None:
        super().__init__(precision=precision, scale=scale)
        self.precision = precision
        self.scale = scale
        self._quantum = Decimal(1).scaleb(-scale)

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "sqlite":
            # asdecimal=False avoids SQLAlchemy's float->Decimal warning; we convert ourselves.
            return dialect.type_descriptor(Numeric(self.precision, self.scale, asdecimal=False))
        return dialect.type_descriptor(Numeric(self.precision, self.scale))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        quantized = to_decimal(value).quantize(self._quantum, rounding=ROUND_HALF_UP)
        return float(quantized) if dialect.name == "sqlite" else quantized

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return to_decimal(value).quantize(self._quantum, rounding=ROUND_HALF_UP)


def Hours(precision: int = 7) -> DecimalType:  # noqa: N802 - reads like a type
    """Hours with 2 decimals (canonical capacity unit, BR-CAP-001)."""
    return DecimalType(precision, 2)


def Ratio() -> DecimalType:  # noqa: N802
    """Dimensionless ratio with 4 decimals (e.g. 0.8750)."""
    return DecimalType(6, 4)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        utc = value.astimezone(UTC)
        return utc.replace(tzinfo=None) if dialect.name == "sqlite" else utc

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):  # SQLite server default CURRENT_TIMESTAMP
            value = datetime.fromisoformat(value)
        result: datetime = value
        return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


# none_as_null=True: Python None is stored as SQL NULL (not the JSON text 'null'), so
# "IS NULL" checks such as ck_audit_event_state_by_action behave as expected.
JSONType = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def enum_type(enum_cls: type[StrEnum], name: str) -> Enum:
    """``VARCHAR`` sized to the longest value plus a named ``CHECK`` constraint."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=max(len(m.value) for m in enum_cls),
        values_callable=lambda e: [m.value for m in e],
    )

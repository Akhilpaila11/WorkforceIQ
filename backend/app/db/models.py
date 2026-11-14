"""Platform tables shared by every module: audit_event, id_sequence, dataset_metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Identity, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now
from app.db.types import JSONType, UTCDateTime, enum_type
from app.domain.enums import AuditAction

# BIGINT identity on PostgreSQL; INTEGER PRIMARY KEY (rowid alias, auto-increment) on SQLite.
AuditPk = BigInteger().with_variant(Integer(), "sqlite")


class AuditEvent(Base):
    """Append-only change history. A database trigger rejects UPDATE and DELETE."""

    __tablename__ = "audit_event"
    __table_args__ = (
        CheckConstraint(
            "(action = 'CREATE' AND before_state IS NULL AND after_state IS NOT NULL)"
            " OR (action = 'DELETE' AND after_state IS NULL AND before_state IS NOT NULL)"
            " OR (action IN ('UPDATE', 'STATUS_CHANGE')"
            " AND before_state IS NOT NULL AND after_state IS NOT NULL)",
            name="state_by_action",
        ),
        Index("ix_audit_event_entity", "entity_type", "entity_id", "occurred_at"),
        {"comment": "Immutable audit trail of every change to business records (A-29)."},
    )

    audit_id: Mapped[int] = mapped_column(
        AuditPk, Identity(), primary_key=True, comment="Monotonic event number."
    )
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="When the change happened (UTC).",
    )
    actor: Mapped[str] = mapped_column(String(100), comment="Who made the change (X-Actor).")
    request_id: Mapped[str | None] = mapped_column(
        String(64), comment="Correlation ID of the HTTP request, if any."
    )
    entity_type: Mapped[str] = mapped_column(String(40), comment="Table name of the record.")
    entity_id: Mapped[str] = mapped_column(String(120), comment="Primary key of the record.")
    action: Mapped[AuditAction] = mapped_column(
        enum_type(AuditAction, "audit_action"), comment="Kind of change."
    )
    before_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSONType, comment="Column values before the change (null for CREATE)."
    )
    after_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSONType, comment="Column values after the change (null for DELETE)."
    )
    reason: Mapped[str | None] = mapped_column(
        Text, comment="Why, e.g. override_reason (BR-ALC-005)."
    )


class IdSequence(Base):
    """Portable replacement for PostgreSQL sequences (decision A-38)."""

    __tablename__ = "id_sequence"
    __table_args__ = (
        CheckConstraint("last_value >= 0", name="last_value_non_negative"),
        {"comment": "Last issued sequence number per ID prefix (EMP, PRJ, ALLOC, ...)."},
    )

    prefix: Mapped[str] = mapped_column(
        String(10), primary_key=True, comment="ID prefix, e.g. EMP or ALLOC."
    )
    last_value: Mapped[int] = mapped_column(
        Integer, comment="Highest sequence number issued so far."
    )


class DatasetMetadata(Base):
    """Key/value facts about the loaded dataset (mode, seed, as_of_date, manifest hash)."""

    __tablename__ = "dataset_metadata"
    __table_args__ = ({"comment": "Facts about the loaded synthetic dataset."},)

    key: Mapped[str] = mapped_column(String(60), primary_key=True, comment="Metadata key.")
    value: Mapped[str] = mapped_column(Text, comment="Metadata value (text).")

"""Project tables: project, demand_plan, demand_skill_requirement, demand_actual, allocation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy import text as sql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.constraints import between_check, date_order_check, id_format_check, proficiency_check
from app.db.types import Hours, enum_type
from app.domain.enums import (
    ActualSource,
    AllocationStatus,
    AllocationType,
    DemandSource,
    DemandStatus,
    ProjectPriority,
    ProjectStatus,
    RequirementType,
)
from app.domain.ids import DEMAND_ID_LENGTH, EntityKind

HOURS = {"units": "hours"}


class Project(TimestampMixin, Base):
    __tablename__ = "project"
    __table_args__ = (
        id_format_check("project_id", EntityKind.PROJECT),
        date_order_check("start_date", "end_date", name="project_dates"),
        CheckConstraint(
            "closed_date IS NULL OR closed_date >= start_date", name="closed_after_start"
        ),
        CheckConstraint(
            "(status IN ('COMPLETED', 'CANCELLED') AND closed_date IS NOT NULL)"
            " OR (status NOT IN ('COMPLETED', 'CANCELLED') AND closed_date IS NULL)",
            name="closed_date_status",
        ),
        {"comment": "Client or internal projects that create demand."},
    )

    project_id: Mapped[str] = mapped_column(
        String(15), primary_key=True, comment="Immutable ID, PRJ-<start year>-000001."
    )
    name: Mapped[str] = mapped_column(String(150), comment="Project name (synthetic).")
    client_name: Mapped[str | None] = mapped_column(
        String(150), comment="Client name (synthetic); null for internal projects."
    )
    business_unit: Mapped[str] = mapped_column(String(60), comment="Owning business unit.")
    priority: Mapped[ProjectPriority] = mapped_column(
        enum_type(ProjectPriority, "project_priority"),
        index=True,
        comment="Processing order for gap analysis (BR-PRJ-002).",
    )
    status: Mapped[ProjectStatus] = mapped_column(
        enum_type(ProjectStatus, "project_status"),
        index=True,
        comment="Lifecycle status (BR-PRJ-001).",
    )
    start_date: Mapped[date] = mapped_column(Date, comment="Planned start (inclusive).")
    end_date: Mapped[date] = mapped_column(Date, comment="Planned end (inclusive).")
    closed_date: Mapped[date | None] = mapped_column(
        Date, comment="Set iff status is COMPLETED or CANCELLED."
    )

    demand_lines: Mapped[list[DemandPlan]] = relationship(back_populates="project")
    allocations: Mapped[list[Allocation]] = relationship(back_populates="project")


class DemandPlan(TimestampMixin, Base):
    """One weekly demand line (planned demand, BR-FCT-001)."""

    __tablename__ = "demand_plan"
    __table_args__ = (
        CheckConstraint(
            "demand_id LIKE 'DEM-' || project_id || '-%'"
            f" AND length(demand_id) = {DEMAND_ID_LENGTH}",
            name="demand_id_format",
        ),
        between_check("iso_week", 1, 53),
        between_check("iso_year", 2000, 2100),
        between_check("line_no", 1, 99),
        CheckConstraint("required_hours > 0", name="required_hours_positive"),
        CheckConstraint("headcount >= 1", name="headcount_positive"),
        CheckConstraint("required_hours <= headcount * 40", name="hours_within_headcount"),
        Index("uq_demand_plan_line", "project_id", "iso_year", "iso_week", "line_no", unique=True),
        Index("ix_demand_plan_project_week", "project_id", "week_start_date"),
        Index("ix_demand_plan_role_week", "role_id", "week_start_date"),
        {
            "comment": "Weekly demand lines. The business key is NOT unique on purpose:"
            " duplicates are detected, not prevented (BR-DEM-004)."
        },
    )
    __immutable__ = (
        "project_id",
        "role_id",
        "iso_year",
        "iso_week",
        "week_start_date",
        "line_no",
    )

    demand_id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        comment="Immutable ID, DEM-<project_id>-<ISO year>W<ISO week>-<line> (BR-DEM-005).",
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.project_id", ondelete="RESTRICT"), comment="Project."
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("role.role_id", ondelete="RESTRICT"), comment="Requested role."
    )
    iso_year: Mapped[int] = mapped_column(SmallInteger, comment="ISO-8601 year of the week.")
    iso_week: Mapped[int] = mapped_column(SmallInteger, comment="ISO-8601 week number 1-53.")
    week_start_date: Mapped[date] = mapped_column(
        Date, comment="Monday of the ISO week (validated in the domain layer)."
    )
    line_no: Mapped[int] = mapped_column(
        SmallInteger, comment="1-based line number within project + week."
    )
    required_hours: Mapped[Decimal] = mapped_column(
        Hours(7), comment="Planned hours for the week.", info=HOURS
    )
    headcount: Mapped[int] = mapped_column(
        SmallInteger,
        comment="Number of people expected to share the hours.",
        info={"units": "people"},
    )
    status: Mapped[DemandStatus] = mapped_column(
        enum_type(DemandStatus, "demand_status"),
        index=True,
        comment="Lifecycle status (BR-DEM-002); counted statuses in BR-DEM-003.",
    )
    source: Mapped[DemandSource] = mapped_column(
        enum_type(DemandSource, "demand_source"), comment="Where the line came from."
    )

    project: Mapped[Project] = relationship(back_populates="demand_lines")
    skill_requirements: Mapped[list[DemandSkillRequirement]] = relationship(
        back_populates="demand", cascade="all, delete-orphan"
    )


class DemandSkillRequirement(TimestampMixin, Base):
    """Bridge DemandPlan <-> Skill (M:N): exactly one PRIMARY per line (BR-DEM-001)."""

    __tablename__ = "demand_skill_requirement"
    __table_args__ = (
        proficiency_check("min_proficiency"),
        Index(
            "uq_demand_skill_requirement_one_primary",
            "demand_id",
            unique=True,
            sqlite_where=sql("requirement_type = 'PRIMARY'"),
            postgresql_where=sql("requirement_type = 'PRIMARY'"),
        ),
        {"comment": "Skills required by a demand line (1 PRIMARY, 0-2 SECONDARY)."},
    )
    __immutable__ = ("demand_id", "skill_id")

    demand_id: Mapped[str] = mapped_column(
        ForeignKey("demand_plan.demand_id", ondelete="RESTRICT"),
        primary_key=True,
        comment="Demand line.",
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skill.skill_id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
        comment="Required skill.",
    )
    requirement_type: Mapped[RequirementType] = mapped_column(
        enum_type(RequirementType, "requirement_type"),
        comment="PRIMARY = mandatory, drives gaps; SECONDARY = preferred, affects ranking.",
    )
    min_proficiency: Mapped[int] = mapped_column(
        SmallInteger,
        comment="Minimum level for eligibility.",
        info={"units": "proficiency level (1-5)"},
    )

    demand: Mapped[DemandPlan] = relationship(back_populates="skill_requirements")


class DemandActual(TimestampMixin, Base):
    """Actual demand (synthetic timesheets) per project x role x week (BR-FCT-001)."""

    __tablename__ = "demand_actual"
    __table_args__ = (
        CheckConstraint("actual_hours >= 0", name="actual_hours_non_negative"),
        between_check("iso_week", 1, 53),
        Index("ix_demand_actual_role_week", "role_id", "week_start_date"),
        {
            "comment": "Actual hours. Forecast methods may read only weeks before the"
            " forecast origin (BR-FCT-004)."
        },
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.project_id", ondelete="RESTRICT"),
        primary_key=True,
        comment="Project.",
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("role.role_id", ondelete="RESTRICT"), primary_key=True, comment="Role."
    )
    week_start_date: Mapped[date] = mapped_column(
        Date, primary_key=True, comment="Monday of the ISO week."
    )
    iso_year: Mapped[int] = mapped_column(SmallInteger, comment="ISO-8601 year of the week.")
    iso_week: Mapped[int] = mapped_column(SmallInteger, comment="ISO-8601 week number.")
    actual_hours: Mapped[Decimal] = mapped_column(
        Hours(7), comment="Hours actually worked.", info=HOURS
    )
    source: Mapped[ActualSource] = mapped_column(
        enum_type(ActualSource, "actual_source"), comment="Origin of the actuals."
    )


class Allocation(TimestampMixin, Base):
    """Bridge Employee <-> Project (M:N, dated) with the role played."""

    __tablename__ = "allocation"
    __table_args__ = (
        id_format_check("allocation_id", EntityKind.ALLOCATION),
        date_order_check("start_date", "end_date"),
        CheckConstraint("hours_per_week > 0 AND hours_per_week <= 60", name="hours_per_week_range"),
        Index("ix_allocation_employee_dates", "employee_id", "start_date", "end_date"),
        Index("ix_allocation_project_role", "project_id", "role_id"),
        {
            "comment": "Employee assignments. Over-allocation and overlaps are detected,"
            " not prevented, at DB level (A-17)."
        },
    )
    __immutable__ = ("employee_id", "project_id")

    allocation_id: Mapped[str] = mapped_column(
        String(17), primary_key=True, comment="Immutable ID, ALLOC-<start year>-000001."
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employee.employee_id", ondelete="RESTRICT"), comment="Allocated employee."
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.project_id", ondelete="RESTRICT"), comment="Project."
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("role.role_id", ondelete="RESTRICT"), comment="Role played on the project."
    )
    start_date: Mapped[date] = mapped_column(Date, comment="First day (inclusive).")
    end_date: Mapped[date] = mapped_column(Date, comment="Last day (inclusive).")
    hours_per_week: Mapped[Decimal] = mapped_column(
        Hours(5),
        comment="Booked hours per full week; prorated by working days (BR-CAP-008).",
        info=HOURS,
    )
    allocation_type: Mapped[AllocationType] = mapped_column(
        enum_type(AllocationType, "allocation_type"),
        comment="DEDICATED = exclusive (BR-ALC-003); SHARED = may overlap.",
    )
    status: Mapped[AllocationStatus] = mapped_column(
        enum_type(AllocationStatus, "allocation_status"),
        index=True,
        comment="Lifecycle status (BR-ALC-002).",
    )
    notes: Mapped[str | None] = mapped_column(Text, comment="Optional note.")

    project: Mapped[Project] = relationship(back_populates="allocations")

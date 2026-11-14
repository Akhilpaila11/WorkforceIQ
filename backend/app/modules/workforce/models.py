"""Workforce tables: role, skill, role_skill, employee, employee_skill, availability, training.

ORM classes describe *structure* only (columns, keys, constraints, relationships).
Business rules live in services and engines.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    false,
    true,
)
from sqlalchemy import Text as SAText
from sqlalchemy import text as sql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.constraints import date_order_check, id_format_check, proficiency_check
from app.db.types import Hours, enum_type
from app.domain.enums import (
    AssessmentSource,
    AvailabilityStatus,
    AvailabilityType,
    EmployeeStatus,
    RecordedSkillStatus,
    RoleFamily,
    Seniority,
    SkillCategory,
    SkillImportance,
    TrainingStatus,
    TrainingType,
)
from app.domain.ids import EntityKind

HOURS = {"units": "hours"}
LEVEL = {"units": "proficiency level (1-5)"}


class Role(TimestampMixin, Base):
    __tablename__ = "role"
    __table_args__ = (
        id_format_check("role_id", EntityKind.ROLE),
        {"comment": "Job roles employees hold and demand lines request."},
    )

    role_id: Mapped[str] = mapped_column(
        String(10), primary_key=True, comment="Immutable role ID, ROL-000001."
    )
    code: Mapped[str] = mapped_column(
        String(40), unique=True, comment="Upper snake-case code, e.g. BACKEND_ENGINEER."
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, comment="Display name.")
    role_family: Mapped[RoleFamily] = mapped_column(
        enum_type(RoleFamily, "role_family"),
        comment="Family used for eligibility (BR-SKL-006: same family required).",
    )
    description: Mapped[str | None] = mapped_column(SAText, comment="Free-text description.")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), comment="False = deactivated role."
    )

    employees: Mapped[list[Employee]] = relationship(back_populates="role")
    role_skills: Mapped[list[RoleSkill]] = relationship(back_populates="role")


class Skill(TimestampMixin, Base):
    __tablename__ = "skill"
    __table_args__ = (
        id_format_check("skill_id", EntityKind.SKILL),
        CheckConstraint(
            "(requires_certification AND validity_months IS NOT NULL)"
            " OR (NOT requires_certification AND validity_months IS NULL)",
            name="certification_validity",
        ),
        CheckConstraint(
            "validity_months IS NULL OR (validity_months >= 1 AND validity_months <= 60)",
            name="validity_months_range",
        ),
        {"comment": "Skills that employees hold and demand lines require."},
    )

    skill_id: Mapped[str] = mapped_column(
        String(10), primary_key=True, comment="Immutable skill ID, SKL-000001."
    )
    code: Mapped[str] = mapped_column(String(60), unique=True, comment="Unique skill code.")
    name: Mapped[str] = mapped_column(String(120), unique=True, comment="Display name.")
    category: Mapped[SkillCategory] = mapped_column(
        enum_type(SkillCategory, "skill_category"), comment="Skill category."
    )
    requires_certification: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        comment="True = proficiency expires (BR-SKL-005).",
    )
    validity_months: Mapped[int | None] = mapped_column(
        SmallInteger,
        comment="Certificate validity; required iff requires_certification (BR-SKL-005).",
        info={"units": "months"},
    )
    description: Mapped[str | None] = mapped_column(SAText, comment="Free-text description.")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), comment="False = deactivated skill."
    )

    employee_skills: Mapped[list[EmployeeSkill]] = relationship(back_populates="skill")
    role_skills: Mapped[list[RoleSkill]] = relationship(back_populates="skill")


class RoleSkill(TimestampMixin, Base):
    """Bridge Role <-> Skill (M:N): skills expected for a role."""

    __tablename__ = "role_skill"
    __table_args__ = (
        proficiency_check("typical_min_proficiency"),
        {"comment": "Bridge role <-> skill: skills a role is expected to have."},
    )
    __immutable__ = ("role_id", "skill_id")

    role_id: Mapped[str] = mapped_column(
        ForeignKey("role.role_id", ondelete="RESTRICT"), primary_key=True, comment="Role."
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skill.skill_id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
        comment="Skill.",
    )
    importance: Mapped[SkillImportance] = mapped_column(
        enum_type(SkillImportance, "skill_importance"), comment="CORE or SUPPORTING."
    )
    typical_min_proficiency: Mapped[int] = mapped_column(
        SmallInteger, comment="Typical minimum level for the role.", info=LEVEL
    )

    role: Mapped[Role] = relationship(back_populates="role_skills")
    skill: Mapped[Skill] = relationship(back_populates="role_skills")


class Employee(TimestampMixin, Base):
    __tablename__ = "employee"
    __table_args__ = (
        id_format_check("employee_id", EntityKind.EMPLOYEE),
        date_order_check("hire_date", "termination_date", name="employment_dates"),
        CheckConstraint(
            "status <> 'TERMINATED' OR termination_date IS NOT NULL",
            name="terminated_has_date",
        ),
        {"comment": "Employees (synthetic). Working hours live in availability (A-06)."},
    )

    employee_id: Mapped[str] = mapped_column(
        String(10), primary_key=True, comment="Immutable employee ID, EMP-000001."
    )
    first_name: Mapped[str] = mapped_column(String(60), comment="Given name (synthetic).")
    last_name: Mapped[str] = mapped_column(String(60), comment="Family name (synthetic).")
    email: Mapped[str] = mapped_column(
        String(254), unique=True, comment="Unique email; @example.com in synthetic data."
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("role.role_id", ondelete="RESTRICT"), index=True, comment="Primary role."
    )
    seniority: Mapped[Seniority] = mapped_column(
        enum_type(Seniority, "seniority"), comment="Seniority grade."
    )
    location: Mapped[str] = mapped_column(String(60), comment="Work location (synthetic city).")
    hire_date: Mapped[date] = mapped_column(Date, comment="First working day.")
    termination_date: Mapped[date | None] = mapped_column(
        Date, comment="Last working day; null while employed."
    )
    status: Mapped[EmployeeStatus] = mapped_column(
        enum_type(EmployeeStatus, "employee_status"),
        index=True,
        comment="Lifecycle status; must agree with dates (BR-EMP-001).",
    )

    role: Mapped[Role] = relationship(back_populates="employees")
    skills: Mapped[list[EmployeeSkill]] = relationship(
        back_populates="employee", order_by="EmployeeSkill.effective_from"
    )
    availability: Mapped[list[Availability]] = relationship(
        back_populates="employee", order_by="Availability.start_date"
    )
    trainings: Mapped[list[Training]] = relationship(back_populates="employee")


class EmployeeSkill(TimestampMixin, Base):
    """Bridge Employee <-> Skill (M:N), versioned (SCD type 2, BR-SKL-008)."""

    __tablename__ = "employee_skill"
    __table_args__ = (
        id_format_check("employee_skill_id", EntityKind.EMPLOYEE_SKILL),
        proficiency_check("proficiency_level"),
        CheckConstraint(
            "expiry_date IS NULL OR expiry_date > last_verified_date", name="expiry_after_verified"
        ),
        date_order_check("effective_from", "effective_to", name="effective_dates"),
        Index(
            "uq_employee_skill_current",
            "employee_id",
            "skill_id",
            unique=True,
            sqlite_where=sql("effective_to IS NULL"),
            postgresql_where=sql("effective_to IS NULL"),
        ),
        Index(
            "ix_employee_skill_current_skill_level",
            "skill_id",
            "proficiency_level",
            sqlite_where=sql("effective_to IS NULL"),
            postgresql_where=sql("effective_to IS NULL"),
        ),
        Index(
            "uq_employee_skill_version",
            "employee_id",
            "skill_id",
            "effective_from",
            unique=True,
        ),
        {"comment": "Employee skill profile versions; one current version per employee+skill."},
    )
    __immutable__ = ("employee_id", "skill_id", "effective_from")

    employee_skill_id: Mapped[str] = mapped_column(
        String(10), primary_key=True, comment="Immutable version ID, ESK-000001."
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        index=True,
        comment="Employee holding the skill.",
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skill.skill_id", ondelete="RESTRICT"), comment="Skill held."
    )
    proficiency_level: Mapped[int] = mapped_column(
        SmallInteger, comment="1 Awareness .. 5 Expert (BR-SKL-001).", info=LEVEL
    )
    assessment_source: Mapped[AssessmentSource] = mapped_column(
        enum_type(AssessmentSource, "assessment_source"), comment="How the level was assessed."
    )
    last_verified_date: Mapped[date] = mapped_column(
        Date, comment="Date the level was last verified (freshness, BR-SKL-002)."
    )
    expiry_date: Mapped[date | None] = mapped_column(
        Date, comment="Certificate expiry; required for certification skills (BR-SKL-005)."
    )
    recorded_status: Mapped[RecordedSkillStatus] = mapped_column(
        enum_type(RecordedSkillStatus, "recorded_skill_status"),
        comment="Status flag from the source system; informational only (BR-SKL-003).",
    )
    effective_from: Mapped[date] = mapped_column(Date, comment="First day this version applies.")
    effective_to: Mapped[date | None] = mapped_column(
        Date, comment="Last day this version applies; null = current version."
    )

    employee: Mapped[Employee] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship(back_populates="employee_skills")


class Availability(TimestampMixin, Base):
    """Effective-dated work schedules and leave (A-06, BR-CAP-003..005)."""

    __tablename__ = "availability"
    __table_args__ = (
        id_format_check("availability_id", EntityKind.AVAILABILITY),
        date_order_check("start_date", "end_date"),
        CheckConstraint(
            "(availability_type = 'WORK_SCHEDULE' AND weekly_hours IS NOT NULL"
            " AND weekly_hours >= 8 AND weekly_hours <= 40 AND hours_per_day IS NULL)"
            " OR (availability_type <> 'WORK_SCHEDULE' AND weekly_hours IS NULL"
            " AND end_date IS NOT NULL"
            " AND (hours_per_day IS NULL OR (hours_per_day > 0 AND hours_per_day <= 8)))",
            name="type_fields",
        ),
        Index("ix_availability_employee_dates", "employee_id", "start_date", "end_date"),
        {"comment": "Work schedules (weekly hours) and leave (reduces capacity)."},
    )
    __immutable__ = ("employee_id", "availability_type")

    availability_id: Mapped[str] = mapped_column(
        String(15), primary_key=True, comment="Immutable ID, AVL-<start year>-000001."
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employee.employee_id", ondelete="RESTRICT"), comment="Employee."
    )
    availability_type: Mapped[AvailabilityType] = mapped_column(
        enum_type(AvailabilityType, "availability_type"),
        index=True,
        comment="WORK_SCHEDULE or a leave type.",
    )
    start_date: Mapped[date] = mapped_column(Date, comment="First day (inclusive).")
    end_date: Mapped[date | None] = mapped_column(
        Date, comment="Last day (inclusive); null only for an open-ended work schedule."
    )
    weekly_hours: Mapped[Decimal | None] = mapped_column(
        Hours(5),
        comment="Contracted hours per week; WORK_SCHEDULE only, 8-40 (BR-CAP-004).",
        info=HOURS,
    )
    hours_per_day: Mapped[Decimal | None] = mapped_column(
        Hours(4),
        comment="Partial-day leave hours; null = full day (BR-CAP-005). Leave only.",
        info=HOURS,
    )
    status: Mapped[AvailabilityStatus] = mapped_column(
        enum_type(AvailabilityStatus, "availability_status"),
        comment="Only APPROVED rows affect capacity.",
    )
    reason: Mapped[str | None] = mapped_column(String(200), comment="Optional note.")

    employee: Mapped[Employee] = relationship(back_populates="availability")


class Training(TimestampMixin, Base):
    __tablename__ = "training"
    __table_args__ = (
        id_format_check("training_id", EntityKind.TRAINING),
        proficiency_check("target_proficiency"),
        date_order_check("start_date", "end_date"),
        CheckConstraint("hours_per_week > 0 AND hours_per_week <= 40", name="hours_per_week_range"),
        CheckConstraint(
            "(status = 'COMPLETED' AND completion_date IS NOT NULL)"
            " OR (status <> 'COMPLETED' AND completion_date IS NULL)",
            name="completion_date_status",
        ),
        CheckConstraint(
            "completion_date IS NULL OR completion_date >= start_date",
            name="completion_after_start",
        ),
        CheckConstraint(
            "outcome_employee_skill_id IS NULL OR status = 'COMPLETED'",
            name="outcome_only_when_completed",
        ),
        {"comment": "Training activities; consume capacity (BR-CAP-006)."},
    )
    __immutable__ = ("employee_id", "skill_id")

    training_id: Mapped[str] = mapped_column(
        String(15), primary_key=True, comment="Immutable ID, TRN-<start year>-000001."
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employee.employee_id", ondelete="RESTRICT"), index=True, comment="Trainee."
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skill.skill_id", ondelete="RESTRICT"), index=True, comment="Skill trained."
    )
    recommendation_id: Mapped[str | None] = mapped_column(
        ForeignKey("recommendation.recommendation_id", ondelete="RESTRICT"),
        comment="TRAIN recommendation this training implements, if any (BR-REC-006).",
    )
    outcome_employee_skill_id: Mapped[str | None] = mapped_column(
        ForeignKey("employee_skill.employee_skill_id", ondelete="RESTRICT"),
        unique=True,
        comment="Skill version created on completion (BR-TRN-002).",
    )
    training_type: Mapped[TrainingType] = mapped_column(
        enum_type(TrainingType, "training_type"), comment="Kind of training."
    )
    target_proficiency: Mapped[int] = mapped_column(
        SmallInteger, comment="Level reached on completion.", info=LEVEL
    )
    start_date: Mapped[date] = mapped_column(Date, comment="First day (inclusive).")
    end_date: Mapped[date] = mapped_column(Date, comment="Last day (inclusive).")
    hours_per_week: Mapped[Decimal] = mapped_column(
        Hours(5), comment="Weekly time spent; deducted from capacity.", info=HOURS
    )
    status: Mapped[TrainingStatus] = mapped_column(
        enum_type(TrainingStatus, "training_status"),
        index=True,
        comment="Lifecycle status (BR-TRN-001).",
    )
    completion_date: Mapped[date | None] = mapped_column(
        Date, comment="Required iff status is COMPLETED."
    )

    employee: Mapped[Employee] = relationship(back_populates="trainings")
    skill: Mapped[Skill] = relationship()
    outcome_skill_version: Mapped[EmployeeSkill | None] = relationship()

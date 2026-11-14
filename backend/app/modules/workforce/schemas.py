"""Pydantic v2 DTOs for the workforce module: commands, list queries and responses."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.params import DateWindowQuery, EmployeeId, PageQuery, RoleId, SearchText, SkillId
from app.domain.enums import (
    AssessmentSource,
    AvailabilityStatus,
    AvailabilityType,
    EmployeeStatus,
    RecordedSkillStatus,
    RoleFamily,
    Seniority,
    SkillCategory,
    TrainingStatus,
    TrainingType,
)


class SkillAssessmentIn(BaseModel):
    """A new assessment of one employee's skill (creates a new version, BR-SKL-008)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    employee_id: str = Field(pattern=r"^EMP-\d{6}$")
    skill_id: str = Field(pattern=r"^SKL-\d{6}$")
    proficiency_level: int = Field(ge=1, le=5)
    assessment_source: AssessmentSource
    last_verified_date: date
    expiry_date: date | None = None
    recorded_status: RecordedSkillStatus = RecordedSkillStatus.CURRENT
    effective_from: date

    @model_validator(mode="after")
    def _expiry_after_verification(self) -> SkillAssessmentIn:
        if self.expiry_date is not None and self.expiry_date <= self.last_verified_date:
            raise ValueError("expiry_date must be after last_verified_date (BR-SKL-005)")
        return self


# ------------------------------------------------------------------ list queries (Phase 4)
class EmployeeQuery(PageQuery):
    role_id: RoleId | None = None
    status: EmployeeStatus | None = None
    seniority: Seniority | None = None
    location: str | None = Field(default=None, max_length=100)
    skill_id: SkillId | None = Field(
        default=None, description="Only employees holding a current version of this skill"
    )
    search: SearchText | None = Field(default=None, description="Name or email contains")


class RoleQuery(PageQuery):
    role_family: RoleFamily | None = None
    is_active: bool | None = None


class SkillQuery(PageQuery):
    category: SkillCategory | None = None
    requires_certification: bool | None = None
    is_active: bool | None = None
    search: SearchText | None = Field(default=None, description="Code or name contains")


class EmployeeSkillQuery(PageQuery):
    skill_id: SkillId | None = None
    recorded_status: RecordedSkillStatus | None = None
    min_proficiency: int | None = Field(default=None, ge=1, le=5)
    include_history: bool = Field(
        default=False, description="Also return superseded versions (effective_to set)"
    )


class AvailabilityQuery(DateWindowQuery):
    employee_id: EmployeeId | None = None
    availability_type: AvailabilityType | None = None
    status: AvailabilityStatus | None = None


class TrainingQuery(DateWindowQuery):
    employee_id: EmployeeId | None = None
    skill_id: SkillId | None = None
    training_type: TrainingType | None = None
    status: TrainingStatus | None = None


# ------------------------------------------------------------------ responses (Phase 4)
class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RoleOut(_Out):
    role_id: str
    code: str
    name: str
    role_family: RoleFamily
    description: str | None
    is_active: bool


class SkillOut(_Out):
    skill_id: str
    code: str
    name: str
    category: SkillCategory
    requires_certification: bool
    validity_months: int | None
    description: str | None
    is_active: bool


class SkillRef(_Out):
    skill_id: str
    code: str
    name: str
    category: SkillCategory


class EmployeeOut(_Out):
    employee_id: str
    first_name: str
    last_name: str
    email: str
    role_id: str
    seniority: Seniority
    location: str
    hire_date: date
    termination_date: date | None
    status: EmployeeStatus


class EmployeeDetailOut(EmployeeOut):
    role: RoleOut


class EmployeeSkillOut(_Out):
    employee_skill_id: str
    employee_id: str
    skill: SkillRef
    proficiency_level: int
    assessment_source: AssessmentSource
    last_verified_date: date
    expiry_date: date | None
    recorded_status: RecordedSkillStatus
    effective_from: date
    effective_to: date | None


class AvailabilityOut(_Out):
    availability_id: str
    employee_id: str
    availability_type: AvailabilityType
    start_date: date
    end_date: date | None
    weekly_hours: float | None
    hours_per_day: float | None
    status: AvailabilityStatus
    reason: str | None


class TrainingOut(_Out):
    training_id: str
    employee_id: str
    skill_id: str
    recommendation_id: str | None
    outcome_employee_skill_id: str | None
    training_type: TrainingType
    target_proficiency: int
    start_date: date
    end_date: date
    hours_per_week: float
    status: TrainingStatus
    completion_date: date | None

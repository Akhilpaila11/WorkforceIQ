"""Pydantic v2 DTOs for the projects module: list queries and responses."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.params import (
    DateWindowQuery,
    EmployeeId,
    ProjectId,
    RoleId,
    SearchText,
    SkillId,
)
from app.domain.enums import (
    AllocationStatus,
    AllocationType,
    DemandSource,
    DemandStatus,
    ProjectPriority,
    ProjectStatus,
    RequirementType,
)


# ------------------------------------------------------------------ list queries
class ProjectQuery(DateWindowQuery):
    status: ProjectStatus | None = None
    priority: ProjectPriority | None = None
    business_unit: str | None = Field(default=None, max_length=100)
    search: SearchText | None = Field(default=None, description="Name or client contains")


class DemandQuery(DateWindowQuery):
    """Demand lines of one project; the date window filters on ``week_start_date``."""

    role_id: RoleId | None = None
    skill_id: SkillId | None = Field(
        default=None, description="Lines that require this skill (primary or secondary)"
    )
    status: DemandStatus | None = None
    source: DemandSource | None = None


class AllocationQuery(DateWindowQuery):
    employee_id: EmployeeId | None = None
    project_id: ProjectId | None = None
    role_id: RoleId | None = None
    allocation_type: AllocationType | None = None
    status: AllocationStatus | None = None


# ------------------------------------------------------------------ responses
class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectOut(_Out):
    project_id: str
    name: str
    client_name: str | None
    business_unit: str
    priority: ProjectPriority
    status: ProjectStatus
    start_date: date
    end_date: date
    closed_date: date | None


class SkillRequirementOut(_Out):
    skill_id: str
    requirement_type: RequirementType
    min_proficiency: int


class DemandLineOut(_Out):
    demand_id: str
    project_id: str
    role_id: str
    iso_year: int
    iso_week: int
    week_start_date: date
    line_no: int
    required_hours: float
    headcount: int
    status: DemandStatus
    source: DemandSource
    skill_requirements: list[SkillRequirementOut]

    @field_validator("skill_requirements")
    @classmethod
    def _primary_first(cls, value: list[SkillRequirementOut]) -> list[SkillRequirementOut]:
        return sorted(value, key=lambda r: (r.requirement_type, r.skill_id))


class AllocationOut(_Out):
    allocation_id: str
    employee_id: str
    project_id: str
    role_id: str
    start_date: date
    end_date: date
    hours_per_week: float
    allocation_type: AllocationType
    status: AllocationStatus
    notes: str | None

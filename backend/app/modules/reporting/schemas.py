"""Dashboard summary DTOs (plain totals from the stored records; no analytics)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class Breakdown(BaseModel):
    total: int
    by_status: dict[str, int]


class SkillTotals(BaseModel):
    total: int
    requires_certification: int
    employee_skill_versions: int
    current_employee_skills: int


class DemandTotals(Breakdown):
    required_hours: float
    first_week: date | None
    last_week: date | None


class AllocationTotals(Breakdown):
    by_type: dict[str, int]


class AvailabilityTotals(BaseModel):
    total: int
    by_type: dict[str, int]


class SummaryOut(BaseModel):
    dataset: dict[str, str]
    employees: Breakdown
    roles: int
    skills: SkillTotals
    projects: Breakdown
    demand: DemandTotals
    allocations: AllocationTotals
    availability: AvailabilityTotals
    training: Breakdown

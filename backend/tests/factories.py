"""Valid baseline rows for database tests. Override any field with keyword arguments."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.domain.enums import (
    AllocationStatus,
    AllocationType,
    AssessmentSource,
    AvailabilityStatus,
    AvailabilityType,
    DemandSource,
    DemandStatus,
    EmployeeStatus,
    ProjectPriority,
    ProjectStatus,
    RecordedSkillStatus,
    RequirementType,
    RoleFamily,
    RunStatus,
    RunType,
    Seniority,
    SkillCategory,
)
from app.modules.analytics.models import AnalysisRun
from app.modules.projects.models import Allocation, DemandPlan, DemandSkillRequirement, Project
from app.modules.workforce.models import Availability, Employee, EmployeeSkill, Role, Skill


def role(**kw: Any) -> Role:
    data: dict[str, Any] = {
        "role_id": "ROL-000001",
        "code": "BACKEND_ENGINEER",
        "name": "Backend Engineer",
        "role_family": RoleFamily.ENGINEERING,
    }
    return Role(**(data | kw))


def skill(**kw: Any) -> Skill:
    data: dict[str, Any] = {
        "skill_id": "SKL-000001",
        "code": "PYTHON",
        "name": "Python",
        "category": SkillCategory.PROGRAMMING,
        "requires_certification": False,
        "validity_months": None,
    }
    return Skill(**(data | kw))


def employee(**kw: Any) -> Employee:
    data: dict[str, Any] = {
        "employee_id": "EMP-000001",
        "first_name": "Ada",
        "last_name": "Example",
        "email": "ada.example@example.com",
        "role_id": "ROL-000001",
        "seniority": Seniority.SENIOR,
        "location": "Springfield",
        "hire_date": date(2024, 1, 8),
        "termination_date": None,
        "status": EmployeeStatus.ACTIVE,
    }
    return Employee(**(data | kw))


def employee_skill(**kw: Any) -> EmployeeSkill:
    data: dict[str, Any] = {
        "employee_skill_id": "ESK-000001",
        "employee_id": "EMP-000001",
        "skill_id": "SKL-000001",
        "proficiency_level": 4,
        "assessment_source": AssessmentSource.MANAGER,
        "last_verified_date": date(2025, 6, 2),
        "expiry_date": None,
        "recorded_status": RecordedSkillStatus.CURRENT,
        "effective_from": date(2025, 6, 2),
        "effective_to": None,
    }
    return EmployeeSkill(**(data | kw))


def project(**kw: Any) -> Project:
    data: dict[str, Any] = {
        "project_id": "PRJ-2026-000001",
        "name": "Apollo Platform",
        "client_name": "Example Corp",
        "business_unit": "Digital",
        "priority": ProjectPriority.HIGH,
        "status": ProjectStatus.ACTIVE,
        "start_date": date(2025, 12, 29),
        "end_date": date(2026, 6, 28),
        "closed_date": None,
    }
    return Project(**(data | kw))


def demand(**kw: Any) -> DemandPlan:
    data: dict[str, Any] = {
        "demand_id": "DEM-PRJ-2026-000001-2026W01-01",
        "project_id": "PRJ-2026-000001",
        "role_id": "ROL-000001",
        "iso_year": 2026,
        "iso_week": 1,
        "week_start_date": date(2025, 12, 29),
        "line_no": 1,
        "required_hours": Decimal("80.00"),
        "headcount": 2,
        "status": DemandStatus.APPROVED,
        "source": DemandSource.PROJECT_PLAN,
    }
    return DemandPlan(**(data | kw))


def requirement(**kw: Any) -> DemandSkillRequirement:
    data: dict[str, Any] = {
        "demand_id": "DEM-PRJ-2026-000001-2026W01-01",
        "skill_id": "SKL-000001",
        "requirement_type": RequirementType.PRIMARY,
        "min_proficiency": 3,
    }
    return DemandSkillRequirement(**(data | kw))


def allocation(**kw: Any) -> Allocation:
    data: dict[str, Any] = {
        "allocation_id": "ALLOC-2026-000001",
        "employee_id": "EMP-000001",
        "project_id": "PRJ-2026-000001",
        "role_id": "ROL-000001",
        "start_date": date(2025, 12, 29),
        "end_date": date(2026, 3, 29),
        "hours_per_week": Decimal("32.00"),
        "allocation_type": AllocationType.SHARED,
        "status": AllocationStatus.CONFIRMED,
    }
    return Allocation(**(data | kw))


def schedule(**kw: Any) -> Availability:
    data: dict[str, Any] = {
        "availability_id": "AVL-2024-000001",
        "employee_id": "EMP-000001",
        "availability_type": AvailabilityType.WORK_SCHEDULE,
        "start_date": date(2024, 1, 8),
        "end_date": None,
        "weekly_hours": Decimal("40.00"),
        "hours_per_day": None,
        "status": AvailabilityStatus.APPROVED,
    }
    return Availability(**(data | kw))


def run(**kw: Any) -> AnalysisRun:
    data: dict[str, Any] = {
        "run_id": "RUN-2026-000001",
        "run_type": RunType.GAP_ANALYSIS,
        "status": RunStatus.RUNNING,
        "as_of_date": date(2026, 3, 2),
        "period_start": date(2026, 3, 2),
        "period_end": date(2026, 3, 29),
        "rules_version": "1.0.0",
        "rules_sha256": "0" * 64,
        "parameters": {"demand_basis": "PLANNED"},
        "started_at": datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
        "triggered_by": "test",
    }
    return AnalysisRun(**(data | kw))


def seed_core(session: Session) -> None:
    """Role, skill, employee (+schedule), project and one demand line with its PRIMARY skill."""
    session.add_all([role(), skill()])
    session.flush()
    session.add(employee())
    session.add(project())
    session.flush()
    session.add_all([schedule(), demand()])
    session.flush()
    session.add(requirement())
    session.flush()

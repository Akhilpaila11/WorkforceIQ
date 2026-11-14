"""Workforce endpoints: employees and their skills, roles, skills, availability, training."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.api import deps
from app.core.errors import ERROR_RESPONSES
from app.core.params import EMPLOYEE_ID, PageOut
from app.modules.queries import ChildQueryService, QueryService
from app.modules.workforce.models import (
    Availability,
    Employee,
    EmployeeSkill,
    Role,
    Skill,
    Training,
)
from app.modules.workforce.schemas import (
    AvailabilityOut,
    AvailabilityQuery,
    EmployeeDetailOut,
    EmployeeOut,
    EmployeeQuery,
    EmployeeSkillOut,
    EmployeeSkillQuery,
    RoleOut,
    RoleQuery,
    SkillOut,
    SkillQuery,
    TrainingOut,
    TrainingQuery,
)

router = APIRouter(responses=ERROR_RESPONSES)
EmployeePath = Annotated[str, Path(pattern=EMPLOYEE_ID, examples=["EMP-000001"])]
Employees = Annotated[QueryService[Employee, EmployeeQuery], Depends(deps.employee_service)]


@router.get("/employees", tags=["employees"])
def list_employees(
    query: Annotated[EmployeeQuery, Query()], service: Employees
) -> PageOut[EmployeeOut]:
    return PageOut[EmployeeOut].of(service.list(query))


@router.get("/employees/{employee_id}", tags=["employees"])
def get_employee(employee_id: EmployeePath, service: Employees) -> EmployeeDetailOut:
    return EmployeeDetailOut.model_validate(service.get(employee_id))


@router.get("/employees/{employee_id}/skills", tags=["employees"])
def list_employee_skills(
    employee_id: EmployeePath,
    query: Annotated[EmployeeSkillQuery, Query()],
    service: Annotated[
        ChildQueryService[EmployeeSkill, EmployeeSkillQuery],
        Depends(deps.employee_skill_service),
    ],
) -> PageOut[EmployeeSkillOut]:
    """Current skill versions of one employee (``include_history=true`` adds old versions)."""
    return PageOut[EmployeeSkillOut].of(service.list(employee_id, query))


@router.get("/roles", tags=["catalog"])
def list_roles(
    query: Annotated[RoleQuery, Query()],
    service: Annotated[QueryService[Role, RoleQuery], Depends(deps.role_service)],
) -> PageOut[RoleOut]:
    return PageOut[RoleOut].of(service.list(query))


@router.get("/skills", tags=["catalog"])
def list_skills(
    query: Annotated[SkillQuery, Query()],
    service: Annotated[QueryService[Skill, SkillQuery], Depends(deps.skill_service)],
) -> PageOut[SkillOut]:
    return PageOut[SkillOut].of(service.list(query))


@router.get("/availability", tags=["availability"])
def list_availability(
    query: Annotated[AvailabilityQuery, Query()],
    service: Annotated[
        QueryService[Availability, AvailabilityQuery], Depends(deps.availability_service)
    ],
) -> PageOut[AvailabilityOut]:
    """Work schedules, leave and holidays; the date window keeps overlapping records."""
    return PageOut[AvailabilityOut].of(service.list(query))


@router.get("/training", tags=["training"])
def list_training(
    query: Annotated[TrainingQuery, Query()],
    service: Annotated[QueryService[Training, TrainingQuery], Depends(deps.training_service)],
) -> PageOut[TrainingOut]:
    return PageOut[TrainingOut].of(service.list(query))

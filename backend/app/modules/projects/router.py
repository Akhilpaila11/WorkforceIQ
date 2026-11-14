"""Project endpoints: projects, their weekly demand lines, and allocations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.api import deps
from app.core.errors import ERROR_RESPONSES
from app.core.params import PROJECT_ID, PageOut
from app.modules.projects.models import Allocation, DemandPlan, Project
from app.modules.projects.schemas import (
    AllocationOut,
    AllocationQuery,
    DemandLineOut,
    DemandQuery,
    ProjectOut,
    ProjectQuery,
)
from app.modules.queries import ChildQueryService, QueryService

router = APIRouter(responses=ERROR_RESPONSES)
ProjectPath = Annotated[str, Path(pattern=PROJECT_ID, examples=["PRJ-2026-000001"])]
Projects = Annotated[QueryService[Project, ProjectQuery], Depends(deps.project_service)]


@router.get("/projects", tags=["projects"])
def list_projects(
    query: Annotated[ProjectQuery, Query()], service: Projects
) -> PageOut[ProjectOut]:
    """The date window keeps projects whose start..end period overlaps it."""
    return PageOut[ProjectOut].of(service.list(query))


@router.get("/projects/{project_id}", tags=["projects"])
def get_project(project_id: ProjectPath, service: Projects) -> ProjectOut:
    return ProjectOut.model_validate(service.get(project_id))


@router.get("/projects/{project_id}/demand", tags=["projects"])
def list_project_demand(
    project_id: ProjectPath,
    query: Annotated[DemandQuery, Query()],
    service: Annotated[ChildQueryService[DemandPlan, DemandQuery], Depends(deps.demand_service)],
) -> PageOut[DemandLineOut]:
    """Weekly demand lines with their skill requirements; dates filter ``week_start_date``."""
    return PageOut[DemandLineOut].of(service.list(project_id, query))


@router.get("/allocations", tags=["allocations"])
def list_allocations(
    query: Annotated[AllocationQuery, Query()],
    service: Annotated[QueryService[Allocation, AllocationQuery], Depends(deps.allocation_service)],
) -> PageOut[AllocationOut]:
    """The date window keeps allocations whose start..end period overlaps it."""
    return PageOut[AllocationOut].of(service.list(query))

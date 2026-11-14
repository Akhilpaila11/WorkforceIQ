"""SQLAlchemy repositories for projects, demand lines and allocations."""

from __future__ import annotations

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.repository import Page, SqlAlchemyRepository, equal_to, overlapping
from app.modules.projects.models import Allocation, DemandPlan, DemandSkillRequirement, Project
from app.modules.projects.schemas import AllocationQuery, DemandQuery, ProjectQuery


class SqlProjectRepository(SqlAlchemyRepository[Project]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Project)

    def search(self, query: ProjectQuery) -> Page[Project]:
        conditions = equal_to(
            Project,
            {
                "status": query.status,
                "priority": query.priority,
                "business_unit": query.business_unit,
            },
        )
        conditions += overlapping(
            Project.start_date, Project.end_date, query.date_from, query.date_to
        )
        if query.search is not None:
            conditions.append(
                or_(
                    Project.name.icontains(query.search, autoescape=True),
                    Project.client_name.icontains(query.search, autoescape=True),
                )
            )
        return self._paginate(conditions, page=query.page, page_size=query.page_size)


class SqlDemandRepository(SqlAlchemyRepository[DemandPlan]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, DemandPlan)

    def search_for(self, parent_id: str, query: DemandQuery) -> Page[DemandPlan]:
        conditions: list[ColumnElement[bool]] = [
            DemandPlan.project_id == parent_id,
            *equal_to(
                DemandPlan,
                {"role_id": query.role_id, "status": query.status, "source": query.source},
            ),
        ]
        if query.date_from is not None:
            conditions.append(DemandPlan.week_start_date >= query.date_from)
        if query.date_to is not None:
            conditions.append(DemandPlan.week_start_date <= query.date_to)
        if query.skill_id is not None:
            lines = select(DemandSkillRequirement.demand_id).where(
                DemandSkillRequirement.skill_id == query.skill_id
            )
            conditions.append(DemandPlan.demand_id.in_(lines))
        return self._paginate(
            conditions,
            page=query.page,
            page_size=query.page_size,
            options=[selectinload(DemandPlan.skill_requirements)],
        )


class SqlAllocationRepository(SqlAlchemyRepository[Allocation]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Allocation)

    def search(self, query: AllocationQuery) -> Page[Allocation]:
        conditions = equal_to(
            Allocation,
            {
                "employee_id": query.employee_id,
                "project_id": query.project_id,
                "role_id": query.role_id,
                "allocation_type": query.allocation_type,
                "status": query.status,
            },
        )
        conditions += overlapping(
            Allocation.start_date, Allocation.end_date, query.date_from, query.date_to
        )
        return self._paginate(conditions, page=query.page, page_size=query.page_size)

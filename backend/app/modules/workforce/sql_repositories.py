"""SQLAlchemy implementations of the workforce repository Protocols."""

from __future__ import annotations

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.repository import Page, SqlAlchemyRepository, equal_to, overlapping
from app.modules.workforce.models import (
    Availability,
    Employee,
    EmployeeSkill,
    Role,
    Skill,
    Training,
)
from app.modules.workforce.schemas import (
    AvailabilityQuery,
    EmployeeQuery,
    EmployeeSkillQuery,
    RoleQuery,
    SkillQuery,
    TrainingQuery,
)


class SqlEmployeeRepository(SqlAlchemyRepository[Employee]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Employee)

    def search(self, query: EmployeeQuery) -> Page[Employee]:
        conditions = equal_to(
            Employee,
            {
                "role_id": query.role_id,
                "status": query.status,
                "seniority": query.seniority,
                "location": query.location,
            },
        )
        if query.skill_id is not None:
            holders = select(EmployeeSkill.employee_id).where(
                EmployeeSkill.skill_id == query.skill_id, EmployeeSkill.effective_to.is_(None)
            )
            conditions.append(Employee.employee_id.in_(holders))
        if query.search is not None:
            conditions.append(
                or_(
                    *(
                        col.icontains(query.search, autoescape=True)
                        for col in (Employee.first_name, Employee.last_name, Employee.email)
                    )
                )
            )
        return self._paginate(conditions, page=query.page, page_size=query.page_size)


class SqlRoleRepository(SqlAlchemyRepository[Role]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Role)

    def search(self, query: RoleQuery) -> Page[Role]:
        conditions = equal_to(
            Role, {"role_family": query.role_family, "is_active": query.is_active}
        )
        return self._paginate(conditions, page=query.page, page_size=query.page_size)


class SqlSkillRepository(SqlAlchemyRepository[Skill]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Skill)

    def search(self, query: SkillQuery) -> Page[Skill]:
        conditions = equal_to(
            Skill,
            {
                "category": query.category,
                "requires_certification": query.requires_certification,
                "is_active": query.is_active,
            },
        )
        if query.search is not None:
            conditions.append(
                or_(
                    Skill.code.icontains(query.search, autoescape=True),
                    Skill.name.icontains(query.search, autoescape=True),
                )
            )
        return self._paginate(conditions, page=query.page, page_size=query.page_size)


class SqlEmployeeSkillRepository(SqlAlchemyRepository[EmployeeSkill]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, EmployeeSkill)

    def current_version(self, employee_id: str, skill_id: str) -> EmployeeSkill | None:
        return self._session.scalar(
            select(EmployeeSkill).where(
                EmployeeSkill.employee_id == employee_id,
                EmployeeSkill.skill_id == skill_id,
                EmployeeSkill.effective_to.is_(None),
            )
        )

    def search_for(self, parent_id: str, query: EmployeeSkillQuery) -> Page[EmployeeSkill]:
        conditions: list[ColumnElement[bool]] = [
            EmployeeSkill.employee_id == parent_id,
            *equal_to(
                EmployeeSkill,
                {"skill_id": query.skill_id, "recorded_status": query.recorded_status},
            ),
        ]
        if query.min_proficiency is not None:
            conditions.append(EmployeeSkill.proficiency_level >= query.min_proficiency)
        if not query.include_history:
            conditions.append(EmployeeSkill.effective_to.is_(None))
        return self._paginate(
            conditions,
            page=query.page,
            page_size=query.page_size,
            options=[selectinload(EmployeeSkill.skill)],
        )


class SqlAvailabilityRepository(SqlAlchemyRepository[Availability]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Availability)

    def search(self, query: AvailabilityQuery) -> Page[Availability]:
        conditions = equal_to(
            Availability,
            {
                "employee_id": query.employee_id,
                "availability_type": query.availability_type,
                "status": query.status,
            },
        )
        conditions += overlapping(
            Availability.start_date, Availability.end_date, query.date_from, query.date_to
        )
        return self._paginate(conditions, page=query.page, page_size=query.page_size)


class SqlTrainingRepository(SqlAlchemyRepository[Training]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Training)

    def search(self, query: TrainingQuery) -> Page[Training]:
        conditions = equal_to(
            Training,
            {
                "employee_id": query.employee_id,
                "skill_id": query.skill_id,
                "training_type": query.training_type,
                "status": query.status,
            },
        )
        conditions += overlapping(
            Training.start_date, Training.end_date, query.date_from, query.date_to
        )
        return self._paginate(conditions, page=query.page, page_size=query.page_size)

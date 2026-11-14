"""Dependency inversion in action: the same service runs on in-memory fakes, no database."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.db.base import Base
from app.domain.enums import AssessmentSource, AuditAction, SkillCategory
from app.domain.errors import NotFoundError
from app.domain.ids import EntityKind, format_id
from app.modules.workforce.models import EmployeeSkill, Skill
from app.modules.workforce.schemas import SkillAssessmentIn
from app.modules.workforce.services import EmployeeSkillService


class FakeEmployees:
    def __init__(self, *ids: str) -> None:
        self.ids = set(ids)

    def exists(self, entity_id: str) -> bool:
        return entity_id in self.ids


class FakeSkills:
    def __init__(self, *skills: Skill) -> None:
        self.by_id = {s.skill_id: s for s in skills}

    def get(self, entity_id: str) -> Skill | None:
        return self.by_id.get(entity_id)


class FakeVersions:
    def __init__(self) -> None:
        self.rows: list[EmployeeSkill] = []

    def current_version(self, employee_id: str, skill_id: str) -> EmployeeSkill | None:
        return next(
            (
                r
                for r in self.rows
                if (r.employee_id, r.skill_id) == (employee_id, skill_id) and r.effective_to is None
            ),
            None,
        )

    def add(self, version: EmployeeSkill) -> None:
        self.rows.append(version)


class FakeIds:
    def __init__(self) -> None:
        self.n = 0

    def next_id(self, kind: EntityKind, *, year: int | None = None) -> str:
        self.n += 1
        return format_id(kind, self.n, year=year)


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[AuditAction, str]] = []

    def record(
        self,
        *,
        entity: Base,
        action: AuditAction,
        before: Any,
        actor: str,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.events.append((action, actor))


def make_service() -> tuple[EmployeeSkillService, FakeVersions, FakeAudit]:
    versions, audit = FakeVersions(), FakeAudit()
    python = Skill(
        skill_id="SKL-000001",
        code="PY",
        name="Python",
        category=SkillCategory.PROGRAMMING,
        requires_certification=False,
    )
    service = EmployeeSkillService(
        employees=FakeEmployees("EMP-000001"),
        skills=FakeSkills(python),
        versions=versions,
        ids=FakeIds(),
        audit=audit,
    )
    return service, versions, audit


def cmd(level: int, start: date) -> SkillAssessmentIn:
    return SkillAssessmentIn(
        employee_id="EMP-000001",
        skill_id="SKL-000001",
        proficiency_level=level,
        assessment_source=AssessmentSource.SELF,
        last_verified_date=start,
        effective_from=start,
    )


def test_service_logic_without_database():
    service, versions, audit = make_service()
    service.record_assessment(cmd(2, date(2025, 1, 6)), actor="u")
    service.record_assessment(cmd(3, date(2025, 7, 7)), actor="u")
    assert [(r.employee_skill_id, r.proficiency_level, r.effective_to) for r in versions.rows] == [
        ("ESK-000001", 2, date(2025, 7, 6)),
        ("ESK-000002", 3, None),
    ]
    assert [a for a, _ in audit.events] == [
        AuditAction.CREATE,
        AuditAction.UPDATE,
        AuditAction.CREATE,
    ]


def test_pydantic_validation_of_command():
    with pytest.raises(ValueError, match="proficiency_level"):
        cmd(6, date(2025, 1, 6))
    with pytest.raises(ValueError, match="BR-SKL-005"):
        SkillAssessmentIn(
            employee_id="EMP-000001",
            skill_id="SKL-000001",
            proficiency_level=3,
            assessment_source=AssessmentSource.SELF,
            last_verified_date=date(2025, 1, 6),
            expiry_date=date(2025, 1, 6),
            effective_from=date(2025, 1, 6),
        )


def test_not_found_without_database():
    service, _, _ = make_service()
    with pytest.raises(NotFoundError):
        service.record_assessment(
            cmd(3, date(2025, 1, 6)).model_copy(update={"employee_id": "EMP-000002"}), actor="u"
        )

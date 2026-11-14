"""EmployeeSkillService wired with the real SQLAlchemy repositories (SQLite)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import SqlAlchemyAuditRecorder
from app.db.ids import SqlIdAllocator
from app.db.models import AuditEvent
from app.domain.enums import AssessmentSource, AuditAction
from app.domain.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.domain.ids import EntityKind
from app.modules.workforce.schemas import SkillAssessmentIn
from app.modules.workforce.services import EmployeeSkillService
from app.modules.workforce.sql_repositories import (
    SqlEmployeeRepository,
    SqlEmployeeSkillRepository,
    SqlSkillRepository,
)
from tests import factories as f

pytestmark = pytest.mark.integration


def build_service(session: Session) -> EmployeeSkillService:
    return EmployeeSkillService(
        employees=SqlEmployeeRepository(session),
        skills=SqlSkillRepository(session),
        versions=SqlEmployeeSkillRepository(session),
        ids=SqlIdAllocator(session),
        audit=SqlAlchemyAuditRecorder(session),
    )


def assessment(**kw: object) -> SkillAssessmentIn:
    data: dict[str, object] = {
        "employee_id": "EMP-000001",
        "skill_id": "SKL-000001",
        "proficiency_level": 3,
        "assessment_source": AssessmentSource.MANAGER,
        "last_verified_date": date(2025, 6, 2),
        "effective_from": date(2025, 6, 2),
    }
    return SkillAssessmentIn.model_validate(data | kw)


@pytest.fixture
def service(session: Session) -> EmployeeSkillService:
    f.seed_core(session)
    session.commit()
    return build_service(session)


def test_versioning_closes_previous_version_and_audits(
    session: Session, service: EmployeeSkillService
):
    v1 = service.record_assessment(assessment(), actor="alice")
    v2 = service.record_assessment(
        assessment(
            proficiency_level=4,
            last_verified_date=date(2026, 3, 2),
            effective_from=date(2026, 3, 2),
        ),
        actor="bob",
    )
    session.commit()

    assert (v1.employee_skill_id, v2.employee_skill_id) == ("ESK-000001", "ESK-000002")
    assert v1.effective_to == date(2026, 3, 1)
    assert v2.effective_to is None

    events = session.scalars(select(AuditEvent).order_by(AuditEvent.audit_id)).all()
    assert [(e.action, e.entity_id, e.actor) for e in events] == [
        (AuditAction.CREATE, "ESK-000001", "alice"),
        (AuditAction.UPDATE, "ESK-000001", "bob"),
        (AuditAction.CREATE, "ESK-000002", "bob"),
    ]
    assert events[1].before_state is not None and events[1].after_state is not None
    assert events[1].before_state["effective_to"] is None
    assert events[1].after_state["effective_to"] == "2026-03-01"


def test_new_version_must_start_after_current(service: EmployeeSkillService):
    service.record_assessment(assessment(), actor="a")
    with pytest.raises(ConflictError):
        service.record_assessment(assessment(proficiency_level=5), actor="a")


def test_certification_skill_requires_expiry(session: Session, service: EmployeeSkillService):
    session.add(
        f.skill(
            skill_id="SKL-000002",
            code="AWS_SA",
            name="AWS Solutions Architect",
            requires_certification=True,
            validity_months=36,
        )
    )
    session.flush()
    with pytest.raises(BusinessRuleViolation) as exc:
        service.record_assessment(assessment(skill_id="SKL-000002"), actor="a")
    assert exc.value.rule_id == "BR-SKL-005"
    ok = service.record_assessment(
        assessment(skill_id="SKL-000002", expiry_date=date(2028, 6, 2)), actor="a"
    )
    assert ok.expiry_date == date(2028, 6, 2)


def test_unknown_employee_or_skill(service: EmployeeSkillService):
    with pytest.raises(NotFoundError):
        service.record_assessment(assessment(employee_id="EMP-000999"), actor="a")
    with pytest.raises(NotFoundError):
        service.record_assessment(assessment(skill_id="SKL-000999"), actor="a")


def test_id_allocator_continues_after_seeded_ids(session: Session):
    ids = SqlIdAllocator(session)
    ids.ensure_at_least(EntityKind.EMPLOYEE, 100)  # e.g. after loading 100 seeded employees
    assert ids.next_id(EntityKind.EMPLOYEE) == "EMP-000101"
    assert ids.next_id(EntityKind.PROJECT, year=2026) == "PRJ-2026-000001"
    assert ids.next_id(EntityKind.PROJECT, year=2027) == "PRJ-2027-000002"  # global sequence

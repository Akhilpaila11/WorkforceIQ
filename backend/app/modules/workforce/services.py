"""Workforce use-cases.

:class:`EmployeeSkillService` depends only on Protocols (Dependency Inversion); the
composition root (Phase 4: ``app/api/deps.py``) passes SQLAlchemy implementations, tests may
pass in-memory fakes.
"""

from __future__ import annotations

from datetime import timedelta

from app.db.audit import AuditRecorder, snapshot
from app.db.ids import IdAllocator
from app.domain.enums import AuditAction
from app.domain.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.domain.ids import EntityKind
from app.modules.workforce.models import EmployeeSkill
from app.modules.workforce.repositories import (
    EmployeeSkillRepository,
    ExistenceChecker,
    SkillCatalog,
)
from app.modules.workforce.schemas import SkillAssessmentIn


class EmployeeSkillService:
    """Records skill assessments as new versions (BR-SKL-008, BR-SKL-005)."""

    def __init__(
        self,
        *,
        employees: ExistenceChecker,
        skills: SkillCatalog,
        versions: EmployeeSkillRepository,
        ids: IdAllocator,
        audit: AuditRecorder,
    ) -> None:
        self._employees = employees
        self._skills = skills
        self._versions = versions
        self._ids = ids
        self._audit = audit

    def record_assessment(self, cmd: SkillAssessmentIn, *, actor: str) -> EmployeeSkill:
        if not self._employees.exists(cmd.employee_id):
            raise NotFoundError("employee", cmd.employee_id)
        skill = self._skills.get(cmd.skill_id)
        if skill is None:
            raise NotFoundError("skill", cmd.skill_id)
        if skill.requires_certification and cmd.expiry_date is None:
            raise BusinessRuleViolation(
                "BR-SKL-005",
                f"{skill.skill_id} requires certification, so expiry_date is mandatory",
            )

        current = self._versions.current_version(cmd.employee_id, cmd.skill_id)
        if current is not None:
            if cmd.effective_from <= current.effective_from:
                raise ConflictError(
                    "a new skill version must start after the current version",
                    details={
                        "current_version": current.employee_skill_id,
                        "current_effective_from": current.effective_from.isoformat(),
                    },
                )
            before = snapshot(current)
            current.effective_to = cmd.effective_from - timedelta(days=1)
            self._audit.record(
                entity=current, action=AuditAction.UPDATE, before=before, actor=actor
            )

        version = EmployeeSkill(
            employee_skill_id=self._ids.next_id(EntityKind.EMPLOYEE_SKILL),
            effective_to=None,
            **cmd.model_dump(),
        )
        self._versions.add(version)
        self._audit.record(entity=version, action=AuditAction.CREATE, before=None, actor=actor)
        return version

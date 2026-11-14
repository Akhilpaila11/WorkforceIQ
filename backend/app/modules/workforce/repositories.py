"""Repository interfaces (Protocols) the workforce services depend on."""

from __future__ import annotations

from typing import Protocol

from app.modules.workforce.models import EmployeeSkill, Skill


class ExistenceChecker(Protocol):
    def exists(self, entity_id: str) -> bool: ...


class SkillCatalog(Protocol):
    def get(self, entity_id: str) -> Skill | None: ...


class EmployeeSkillRepository(Protocol):
    def current_version(self, employee_id: str, skill_id: str) -> EmployeeSkill | None: ...

    def add(self, version: EmployeeSkill) -> None: ...

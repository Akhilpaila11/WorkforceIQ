"""Skill status, eligibility and match score (BR-SKL-002, BR-SKL-006, BR-SKL-007).

The recorded status of a skill is never trusted for eligibility (BR-SKL-003): the effective
status is always derived from the dates of the version in force on the evaluation date.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.domain.enums import EffectiveSkillStatus
from app.modules.analytics.capacity import EmployeeCapacity
from app.modules.analytics.inputs import (
    AnalysisContext,
    AnalysisInputs,
    DemandLineIn,
    EmployeeIn,
    Requirement,
    SkillVersionIn,
)


class SkillStatusEvaluator:
    """BR-SKL-002: first match wins - EXPIRED, PENDING, STALE, VALID."""

    def __init__(self, freshness_days: int) -> None:
        self._freshness = freshness_days

    def status(self, version: SkillVersionIn, on: date) -> EffectiveSkillStatus:
        if version.expiry_date is not None and version.expiry_date < on:
            return EffectiveSkillStatus.EXPIRED
        if version.recorded_status == "PENDING_VERIFICATION":
            return EffectiveSkillStatus.PENDING
        if (on - version.last_verified_date).days > self._freshness:
            return EffectiveSkillStatus.STALE
        return EffectiveSkillStatus.VALID


class SkillBook:
    """Versioned skill history: the version of an employee's skill in force on a date."""

    def __init__(self, versions: tuple[SkillVersionIn, ...]) -> None:
        grouped: dict[tuple[str, str], list[SkillVersionIn]] = defaultdict(list)
        holders: dict[str, set[str]] = defaultdict(set)
        for v in versions:
            grouped[(v.employee_id, v.skill_id)].append(v)
            holders[v.skill_id].add(v.employee_id)
        self._versions = {
            k: sorted(vs, key=lambda v: (v.effective_from, v.employee_skill_id))
            for k, vs in grouped.items()
        }
        self._starts = {k: [v.effective_from for v in vs] for k, vs in self._versions.items()}
        self._holders = {s: sorted(ids) for s, ids in holders.items()}

    def version_on(self, employee_id: str, skill_id: str, on: date) -> SkillVersionIn | None:
        key = (employee_id, skill_id)
        starts = self._starts.get(key)
        if not starts:
            return None
        i = bisect_right(starts, on) - 1
        if i < 0:
            return None
        version = self._versions[key][i]
        if version.effective_to is not None and version.effective_to < on:
            return None
        return version

    def holders(self, skill_id: str) -> list[str]:
        """Employees with any version of the skill, sorted by ID."""
        return self._holders.get(skill_id, [])


@dataclass(frozen=True, slots=True)
class Eligibility:
    eligible: bool
    reason: str  # ELIGIBLE | INACTIVE | ROLE_FAMILY | MISSING_SKILL | LOW_PROFICIENCY | <status>
    proficiency: int | None = None
    status: EffectiveSkillStatus | None = None


@dataclass(frozen=True, slots=True)
class DemandNeed:
    """What a demand line (or an aggregated gap row) asks for."""

    role_id: str
    role_family: str
    primary: Requirement
    secondary: tuple[Requirement, ...] = ()


class EligibilityPolicy:
    """BR-SKL-006 (eligibility) and BR-SKL-007 (match score)."""

    def __init__(
        self,
        ctx: AnalysisContext,
        inputs: AnalysisInputs,
        book: SkillBook,
        capacity: dict[str, EmployeeCapacity],
    ) -> None:
        self._ctx = ctx
        self._inputs = inputs
        self._book = book
        self._capacity = capacity
        self._status = SkillStatusEvaluator(int(ctx.num("BR-SKL-002", "freshness_days")))
        self._same_family = bool(ctx.param("BR-SKL-006", "require_same_role_family"))
        self._eligible_statuses = ctx.names("BR-SKL-006", "eligible_statuses")
        self._w_role = ctx.num("BR-SKL-007", "weight_exact_role")
        self._w_level = ctx.num("BR-SKL-007", "weight_per_level_above_min")
        self._w_secondary = ctx.num("BR-SKL-007", "weight_per_secondary_skill")

    @property
    def status_evaluator(self) -> SkillStatusEvaluator:
        return self._status

    @property
    def book(self) -> SkillBook:
        return self._book

    def need_of(self, line: DemandLineIn) -> DemandNeed:
        family = self._inputs.role_by_id[line.role_id].role_family
        return DemandNeed(line.role_id, family, line.primary, line.secondary)

    def is_active(self, employee_id: str, week: date) -> bool:
        cap = self._capacity.get(employee_id)
        index = self._ctx.week_index.get(week)
        return bool(cap is not None and index is not None and cap.active[index])

    def same_family(self, employee: EmployeeIn, need: DemandNeed) -> bool:
        if not self._same_family:
            return True
        return self._inputs.role_by_id[employee.role_id].role_family == need.role_family

    def check(self, employee_id: str, need: DemandNeed, week: date) -> Eligibility:
        """Evaluated on the week's Monday (``evaluate_on = WEEK_START``)."""
        employee = self._inputs.employee_by_id[employee_id]
        if not self.is_active(employee_id, week):
            return Eligibility(False, "INACTIVE")
        if not self.same_family(employee, need):
            return Eligibility(False, "ROLE_FAMILY")
        version = self._book.version_on(employee_id, need.primary.skill_id, week)
        if version is None:
            return Eligibility(False, "MISSING_SKILL")
        status = self._status.status(version, week)
        level = version.proficiency_level
        if level < need.primary.min_proficiency:
            return Eligibility(False, "LOW_PROFICIENCY", level, status)
        if status.value not in self._eligible_statuses:
            return Eligibility(False, status.value, level, status)
        return Eligibility(True, "ELIGIBLE", level, status)

    def score(self, employee_id: str, need: DemandNeed, week: date, proficiency: int) -> float:
        employee = self._inputs.employee_by_id[employee_id]
        secondary = 0
        for req in need.secondary:
            v = self._book.version_on(employee_id, req.skill_id, week)
            if (
                v is not None
                and v.proficiency_level >= req.min_proficiency
                and self._status.status(v, week) is EffectiveSkillStatus.VALID
            ):
                secondary += 1
        return (
            self._w_role * (employee.role_id == need.role_id)
            + self._w_level * (proficiency - need.primary.min_proficiency)
            + self._w_secondary * secondary
        )

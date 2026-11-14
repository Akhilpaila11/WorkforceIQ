"""Anomaly detection from source records only (BR-UTL-004, BR-SKL-004, BR-DEM-004, BR-ALC-003).

Detectors read the analysis inputs and computed capacity - never ground-truth labels. Each
finding carries the detecting rule, the records involved and the numbers behind it.
``STALE_SKILL`` findings are informational (BR-SKL-002) and are not part of the four
evaluated anomaly types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from app.domain.enums import AnomalyType, EffectiveSkillStatus, FindingSeverity
from app.modules.analytics.capacity import EPS, EmployeeCapacity, prorated_weeks
from app.modules.analytics.demand import DemandSelection
from app.modules.analytics.inputs import AllocationIn, AnalysisContext, AnalysisInputs
from app.modules.analytics.skills import SkillStatusEvaluator


@dataclass(frozen=True)
class Finding:
    anomaly_type: AnomalyType
    rule_id: str
    entity_type: str
    entity_id: str
    severity: FindingSeverity
    message: str
    details: dict[str, Any]
    related_ids: tuple[str, ...] = ()
    week_start_date: date | None = None

    @property
    def evaluation_key(self) -> str:
        """The evaluation unit of docs/03 (employee-week, record ID or sorted pair)."""
        if self.anomaly_type is AnomalyType.ALLOCATION_EXCEEDS_AVAILABILITY:
            assert self.week_start_date is not None
            return f"{self.entity_id}|{self.week_start_date.isoformat()}"
        if self.anomaly_type is AnomalyType.OVERLAPPING_ALLOCATION_CONFLICT:
            return "|".join(sorted([self.entity_id, *self.related_ids]))
        return self.entity_id


@dataclass
class DetectionOutput:
    findings: list[Finding]
    populations: dict[str, int] = field(default_factory=dict)


class Detector(Protocol):
    anomaly_type: AnomalyType

    def detect(self) -> tuple[list[Finding], int]:
        """Findings plus the size of the evaluated population (for true negatives)."""
        ...


class OverallocationDetector:
    """BR-UTL-004: allocated > net + tolerance for an employee-week."""

    anomaly_type = AnomalyType.ALLOCATION_EXCEEDS_AVAILABILITY

    def __init__(
        self,
        ctx: AnalysisContext,
        inputs: AnalysisInputs,
        capacity: dict[str, EmployeeCapacity],
        weekdays: frozenset[int],
        counted_statuses: frozenset[str],
    ) -> None:
        self._ctx, self._inputs, self._capacity = ctx, inputs, capacity
        self._weekdays, self._statuses = weekdays, counted_statuses
        self._tolerance = ctx.num("BR-UTL-004", "tolerance_hours")
        self._high = ctx.num("BR-UTL-004", "high_severity_excess_hours")

    def _allocations_in(self, employee_id: str, week: date) -> list[AllocationIn]:
        return [
            a
            for a in self._inputs.allocations_by_employee.get(employee_id, [])
            if a.status in self._statuses
            and prorated_weeks(a.hours_per_week, a.start_date, a.end_date, [week], self._weekdays)
        ]

    def detect(self) -> tuple[list[Finding], int]:
        findings, population = [], 0
        for employee_id, cap in sorted(self._capacity.items()):
            net, allocated = cap.net, cap.allocated
            for i, week in enumerate(self._ctx.weeks):
                if cap.gross[i] > 0 or allocated[i] > 0:
                    population += 1
                if allocated[i] <= net[i] + self._tolerance + EPS:  # float-safe boundary
                    continue
                excess = float(allocated[i] - net[i])
                ids = tuple(a.allocation_id for a in self._allocations_in(employee_id, week))
                findings.append(
                    Finding(
                        anomaly_type=self.anomaly_type,
                        rule_id="BR-UTL-004",
                        entity_type="employee",
                        entity_id=employee_id,
                        week_start_date=week,
                        related_ids=ids,
                        severity=FindingSeverity.HIGH
                        if excess >= self._high
                        else FindingSeverity.MEDIUM,
                        message=(
                            f"{employee_id} is allocated {allocated[i]:.2f} h in week of "
                            f"{week.isoformat()} but has only {net[i]:.2f} h net available "
                            f"({excess:.2f} h over)."
                        ),
                        details={
                            "gross_hours": round(float(cap.gross[i]), 2),
                            "leave_hours": round(float(cap.leave[i]), 2),
                            "training_hours": round(float(cap.training[i]), 2),
                            "net_hours": round(float(net[i]), 2),
                            "allocated_hours": round(float(allocated[i]), 2),
                            "excess_hours": round(excess, 2),
                            "tolerance_hours": self._tolerance,
                        },
                    )
                )
        return findings, population


class ExpiredSkillDetector:
    """BR-SKL-004: current version recorded CURRENT but EXPIRED at the run's as-of date."""

    anomaly_type = AnomalyType.EXPIRED_SKILL_TREATED_AS_CURRENT

    def __init__(
        self, ctx: AnalysisContext, inputs: AnalysisInputs, status: SkillStatusEvaluator
    ) -> None:
        self._ctx, self._inputs, self._status = ctx, inputs, status

    def detect(self) -> tuple[list[Finding], int]:
        current = [v for v in self._inputs.skill_versions if v.effective_to is None]
        findings = []
        for v in sorted(current, key=lambda v: v.employee_skill_id):
            if v.recorded_status != "CURRENT":
                continue
            if self._status.status(v, self._ctx.as_of) is not EffectiveSkillStatus.EXPIRED:
                continue
            assert v.expiry_date is not None
            days = (self._ctx.as_of - v.expiry_date).days
            findings.append(
                Finding(
                    anomaly_type=self.anomaly_type,
                    rule_id="BR-SKL-004",
                    entity_type="employee_skill",
                    entity_id=v.employee_skill_id,
                    related_ids=(v.employee_id, v.skill_id),
                    severity=FindingSeverity.HIGH,
                    message=(
                        f"{v.employee_id} skill {v.skill_id} is recorded CURRENT but expired on "
                        f"{v.expiry_date.isoformat()} ({days} days before {self._ctx.as_of})."
                    ),
                    details={
                        "recorded_status": v.recorded_status,
                        "effective_status": "EXPIRED",
                        "expiry_date": v.expiry_date.isoformat(),
                        "last_verified_date": v.last_verified_date.isoformat(),
                        "days_expired": days,
                    },
                )
            )
        return findings, len(current)


class StaleSkillDetector:
    """Informational (BR-SKL-002): current version recorded CURRENT but STALE at as-of."""

    anomaly_type = AnomalyType.STALE_SKILL

    def __init__(
        self, ctx: AnalysisContext, inputs: AnalysisInputs, status: SkillStatusEvaluator
    ) -> None:
        self._ctx, self._inputs, self._status = ctx, inputs, status
        self._days = int(ctx.num("BR-SKL-002", "freshness_days"))

    def detect(self) -> tuple[list[Finding], int]:
        current = [v for v in self._inputs.skill_versions if v.effective_to is None]
        findings = []
        for v in sorted(current, key=lambda v: v.employee_skill_id):
            if v.recorded_status != "CURRENT":
                continue
            if self._status.status(v, self._ctx.as_of) is not EffectiveSkillStatus.STALE:
                continue
            age = (self._ctx.as_of - v.last_verified_date).days
            findings.append(
                Finding(
                    anomaly_type=self.anomaly_type,
                    rule_id="BR-SKL-002",
                    entity_type="employee_skill",
                    entity_id=v.employee_skill_id,
                    related_ids=(v.employee_id, v.skill_id),
                    severity=FindingSeverity.LOW,
                    message=(
                        f"{v.employee_id} skill {v.skill_id} is recorded CURRENT but was last "
                        f"verified {age} days ago (> {self._days}); it does not count for "
                        f"eligibility until re-verified."
                    ),
                    details={
                        "last_verified_date": v.last_verified_date.isoformat(),
                        "age_days": age,
                    },
                )
            )
        return findings, len(current)


class DuplicateDemandDetector:
    """BR-DEM-004: every counted line sharing the duplicate key, except the lowest line no."""

    anomaly_type = AnomalyType.DUPLICATE_DEMAND

    def __init__(self, selection: DemandSelection) -> None:
        self._selection = selection

    def detect(self) -> tuple[list[Finding], int]:
        findings = [
            Finding(
                anomaly_type=self.anomaly_type,
                rule_id="BR-DEM-004",
                entity_type="demand_plan",
                entity_id=d.line.demand_id,
                week_start_date=d.line.week_start_date,
                related_ids=(d.kept.demand_id,),
                severity=FindingSeverity.MEDIUM,
                message=(
                    f"{d.line.demand_id} duplicates {d.kept.demand_id} (same project, week, role, "
                    f"primary skill and minimum proficiency); it is excluded from totals."
                ),
                details={
                    "required_hours": d.line.required_hours,
                    "kept_required_hours": d.kept.required_hours,
                    "primary_skill_id": d.line.primary.skill_id,
                    "min_proficiency": d.line.primary.min_proficiency,
                },
            )
            for d in self._selection.duplicates
        ]
        return findings, len(self._selection.counted)


class ConflictDetector:
    """BR-ALC-003: overlapping counted allocations of one employee, one of them DEDICATED."""

    anomaly_type = AnomalyType.OVERLAPPING_ALLOCATION_CONFLICT

    def __init__(
        self, ctx: AnalysisContext, inputs: AnalysisInputs, counted: frozenset[str]
    ) -> None:
        self._inputs = inputs
        self._counted = counted
        self._exclusive = ctx.names("BR-ALC-003", "exclusive_allocation_types")

    def detect(self) -> tuple[list[Finding], int]:
        findings, pairs = [], 0
        for employee_id, rows in sorted(self._inputs.allocations_by_employee.items()):
            ordered = sorted(
                (a for a in rows if a.status in self._counted),
                key=lambda a: (a.start_date, a.allocation_id),
            )
            for i, a in enumerate(ordered):
                for b in ordered[i + 1 :]:
                    if b.start_date > a.end_date:
                        break
                    pairs += 1
                    if not {a.allocation_type, b.allocation_type} & self._exclusive:
                        continue
                    first, second = sorted([a, b], key=lambda x: x.allocation_id)
                    start, end = max(a.start_date, b.start_date), min(a.end_date, b.end_date)
                    findings.append(
                        Finding(
                            anomaly_type=self.anomaly_type,
                            rule_id="BR-ALC-003",
                            entity_type="allocation",
                            entity_id=first.allocation_id,
                            related_ids=(second.allocation_id,),
                            week_start_date=None,
                            severity=FindingSeverity.HIGH,
                            message=(
                                f"{employee_id}: {first.allocation_id} ({first.allocation_type}, "
                                f"{first.project_id}) overlaps {second.allocation_id} "
                                f"({second.allocation_type}, {second.project_id}) from "
                                f"{start.isoformat()} to {end.isoformat()}; a DEDICATED "
                                f"assignment cannot share time."
                            ),
                            details={
                                "employee_id": employee_id,
                                "overlap_start": start.isoformat(),
                                "overlap_end": end.isoformat(),
                                "projects": [first.project_id, second.project_id],
                            },
                        )
                    )
        return findings, pairs


class AnomalyDetectionEngine:
    def __init__(self, detectors: list[Detector]) -> None:
        self._detectors = detectors

    def run(self) -> DetectionOutput:
        output = DetectionOutput(findings=[])
        for detector in self._detectors:
            found, population = detector.detect()
            output.findings += sorted(found, key=lambda f: f.evaluation_key)
            output.populations[detector.anomaly_type.value] = population
        return output

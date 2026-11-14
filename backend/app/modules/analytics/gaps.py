"""Coverage and skill-gap analysis (BR-GAP-001..007, BR-GAP-009).

For every counted, de-duplicated demand line in the analysis window:

* committed = hours of existing counted allocations on the same project, role and week, applied
  to the lines the allocated employee is eligible for (BR-SKL-006), in BR-GAP-001 order and never
  above a line's remaining demand (BR-GAP-002);
* at_risk = allocated hours that cannot count: the employee is ineligible (e.g. expired skill,
  BR-GAP-003) or the hours exceed the employee's net capacity that week (an over-allocated
  employee cannot deliver more than net hours - assumption A-P5-2);
* gap = demand - committed; coverage = committed / demand (BR-GAP-005).

Rows are aggregated per project x role x primary skill x week.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.domain.enums import GapSeverity
from app.modules.analytics.capacity import EPS, EmployeeCapacity, prorated_weeks
from app.modules.analytics.demand import DemandSelector
from app.modules.analytics.inputs import (
    AnalysisContext,
    AnalysisInputs,
    DemandLineIn,
    Requirement,
)
from app.modules.analytics.skills import DemandNeed, EligibilityPolicy

MIN_HOURS = 0.005  # below this a value rounds to 0.00 h when stored
SEVERITY_ORDER = [
    GapSeverity.NONE,
    GapSeverity.LOW,
    GapSeverity.MEDIUM,
    GapSeverity.HIGH,
    GapSeverity.CRITICAL,
]


@dataclass
class GapRow:
    project_id: str
    role_id: str
    skill_id: str
    week_start_date: date
    priority: str
    order: tuple[int, date, str, int]
    need: DemandNeed
    demand_hours: float = 0.0
    committed_hours: float = 0.0
    at_risk_hours: float = 0.0
    reallocated_hours: float = 0.0
    trained_hours: float = 0.0
    hire_hours: float = 0.0
    source_demand_ids: list[str] = field(default_factory=list)
    gap_id: str = ""

    @property
    def gap_hours(self) -> float:
        return max(0.0, self.demand_hours - self.committed_hours)

    @property
    def residual_hours(self) -> float:
        return max(
            0.0, self.gap_hours - self.reallocated_hours - self.trained_hours - self.hire_hours
        )

    @property
    def coverage_ratio(self) -> float:
        return min(1.0, self.committed_hours / self.demand_hours) if self.demand_hours else 1.0


@dataclass
class GapOutput:
    rows: list[GapRow]
    line_demand: dict[str, float]
    unplanned_allocated_hours: float = 0.0


def gap_severity(
    coverage: float, priority: str, bands: dict[str, float], escalate: frozenset[str]
) -> GapSeverity:
    """BR-GAP-006, raised one level (max CRITICAL) for escalated priorities; NONE stays NONE."""
    if coverage >= 1.0 - EPS:
        return GapSeverity.NONE
    if coverage >= bands["low"]:
        level = GapSeverity.LOW
    elif coverage >= bands["medium"]:
        level = GapSeverity.MEDIUM
    elif coverage >= bands["high"]:
        level = GapSeverity.HIGH
    else:
        level = GapSeverity.CRITICAL
    if priority in escalate:
        level = SEVERITY_ORDER[min(len(SEVERITY_ORDER) - 1, SEVERITY_ORDER.index(level) + 1)]
    return level


class GapAnalyzer:
    def __init__(
        self,
        ctx: AnalysisContext,
        inputs: AnalysisInputs,
        selector: DemandSelector,
        policy: EligibilityPolicy,
        capacity: dict[str, EmployeeCapacity],
        weekdays: frozenset[int],
        counted_allocation_statuses: frozenset[str],
    ) -> None:
        self._ctx = ctx
        self._inputs = inputs
        self._selector = selector
        self._policy = policy
        self._capacity = capacity
        self._weekdays = weekdays
        self._alloc_statuses = counted_allocation_statuses

    def _deliverable_share(self, employee_id: str, week: date) -> float:
        """Share of an employee's allocated hours that fits in net capacity that week."""
        cap = self._capacity.get(employee_id)
        index = self._ctx.week_index.get(week)
        if cap is None or index is None:
            return 0.0
        allocated, net = float(cap.allocated[index]), float(cap.net[index])
        return 1.0 if allocated <= net + EPS else max(0.0, net) / allocated

    def _staffing(self) -> dict[tuple[str, str, date], dict[str, float]]:
        staffed: dict[tuple[str, str, date], dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        for a in sorted(self._inputs.allocations, key=lambda a: a.allocation_id):
            if a.status not in self._alloc_statuses:
                continue
            for week, hours in prorated_weeks(
                a.hours_per_week, a.start_date, a.end_date, self._ctx.window, self._weekdays
            ).items():
                staffed[(a.project_id, a.role_id, week)][a.employee_id] += hours
        return staffed

    def run(
        self,
        kept_lines: tuple[DemandLineIn, ...],
        demand_scale: dict[tuple[str, str, date], float] | None = None,
    ) -> GapOutput:
        window = set(self._ctx.window)
        lines = sorted(
            (line for line in kept_lines if line.week_start_date in window),
            key=self._selector.order_key,
        )
        demand: dict[str, float] = {}
        groups: dict[tuple[str, str, date], list[DemandLineIn]] = defaultdict(list)
        for line in lines:
            scale = 1.0
            if demand_scale is not None:  # BR-GAP-009 FORECAST basis
                scale = demand_scale.get((line.project_id, line.role_id, line.week_start_date), 1.0)
            demand[line.demand_id] = line.required_hours * scale
            groups[(line.project_id, line.role_id, line.week_start_date)].append(line)

        committed: dict[str, float] = defaultdict(float)
        at_risk: dict[str, float] = defaultdict(float)
        unplanned = 0.0
        staffing = self._staffing()
        for key in sorted(staffing):
            group = groups.get(key)
            if not group:
                unplanned += sum(staffing[key].values())  # BR-ALC-004 UNPLANNED staffing
                continue
            week = key[2]
            for employee_id, hours in sorted(staffing[key].items()):
                usable = hours * self._deliverable_share(employee_id, week)
                eligible = [
                    line
                    for line in group
                    if self._policy.check(employee_id, self._policy.need_of(line), week).eligible
                ]
                if not eligible:
                    at_risk[self._at_risk_line(employee_id, group, week).demand_id] += hours
                    continue
                at_risk[eligible[0].demand_id] += hours - usable
                for line in eligible:
                    take = min(usable, demand[line.demand_id] - committed[line.demand_id])
                    if take > 0:
                        committed[line.demand_id] += take
                        usable -= take

        return GapOutput(
            rows=self._aggregate(lines, demand, committed, at_risk),
            line_demand=demand,
            unplanned_allocated_hours=unplanned,
        )

    def _at_risk_line(
        self, employee_id: str, group: list[DemandLineIn], week: date
    ) -> DemandLineIn:
        """BR-GAP-003: the line whose primary skill the employee holds, else the first line."""
        for line in group:
            if self._policy.book.version_on(employee_id, line.primary.skill_id, week):
                return line
        return group[0]

    def _aggregate(
        self,
        lines: list[DemandLineIn],
        demand: dict[str, float],
        committed: dict[str, float],
        at_risk: dict[str, float],
    ) -> list[GapRow]:
        rows: dict[tuple[str, str, str, date], GapRow] = {}
        secondary: dict[tuple[str, str, str, date], dict[str, int]] = defaultdict(dict)
        for line in lines:  # already in BR-GAP-001 order
            key = (line.project_id, line.role_id, line.primary.skill_id, line.week_start_date)
            row = rows.get(key)
            if row is None:
                project = self._inputs.project_by_id[line.project_id]
                row = rows[key] = GapRow(
                    project_id=line.project_id,
                    role_id=line.role_id,
                    skill_id=line.primary.skill_id,
                    week_start_date=line.week_start_date,
                    priority=project.priority,
                    order=self._selector.order_key(line),
                    need=self._policy.need_of(line),
                )
            elif line.primary.min_proficiency > row.need.primary.min_proficiency:
                need = row.need
                row.need = DemandNeed(
                    need.role_id,
                    need.role_family,
                    Requirement(need.primary.skill_id, line.primary.min_proficiency),
                    need.secondary,
                )
            for req in line.secondary:
                current = secondary[key].get(req.skill_id, 0)
                secondary[key][req.skill_id] = max(current, req.min_proficiency)
            row.demand_hours += demand[line.demand_id]
            row.committed_hours += committed.get(line.demand_id, 0.0)
            row.at_risk_hours += at_risk.get(line.demand_id, 0.0)
            row.source_demand_ids.append(line.demand_id)
        for key, row in rows.items():
            reqs = tuple(Requirement(s, m) for s, m in sorted(secondary[key].items()))
            row.need = DemandNeed(row.need.role_id, row.need.role_family, row.need.primary, reqs)
        return [
            r for r in sorted(rows.values(), key=lambda r: r.order) if r.demand_hours >= MIN_HOURS
        ]

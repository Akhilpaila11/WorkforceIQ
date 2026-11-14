"""Plain, immutable input records for the analysis engines (no SQLAlchemy, no FastAPI).

``sql_repositories.SqlAnalysisInputs`` builds them from the database; tests build them by hand.
Hours are floats inside the engines (all source hours are multiples of 0.01 h) and are rounded
to 2 decimals only when results are stored (BR-CAP-001).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cached_property

from app.domain.calendar import monday_of
from app.domain.rules_config import RulesConfig


@dataclass(frozen=True, slots=True)
class RoleIn:
    role_id: str
    code: str
    role_family: str


@dataclass(frozen=True, slots=True)
class SkillIn:
    skill_id: str
    code: str
    requires_certification: bool


@dataclass(frozen=True, slots=True)
class EmployeeIn:
    employee_id: str
    role_id: str
    hire_date: date
    termination_date: date | None


@dataclass(frozen=True, slots=True)
class SkillVersionIn:
    employee_skill_id: str
    employee_id: str
    skill_id: str
    proficiency_level: int
    last_verified_date: date
    expiry_date: date | None
    recorded_status: str
    effective_from: date
    effective_to: date | None


@dataclass(frozen=True, slots=True)
class AvailabilityIn:
    availability_id: str
    employee_id: str
    availability_type: str
    start_date: date
    end_date: date | None
    weekly_hours: float | None
    hours_per_day: float | None
    status: str


@dataclass(frozen=True, slots=True)
class TrainingIn:
    training_id: str
    employee_id: str
    skill_id: str
    start_date: date
    end_date: date
    hours_per_week: float
    status: str


@dataclass(frozen=True, slots=True)
class ProjectIn:
    project_id: str
    priority: str
    status: str
    start_date: date
    end_date: date


@dataclass(frozen=True, slots=True)
class Requirement:
    skill_id: str
    min_proficiency: int


@dataclass(frozen=True, slots=True)
class DemandLineIn:
    demand_id: str
    project_id: str
    role_id: str
    week_start_date: date
    line_no: int
    required_hours: float
    status: str
    primary: Requirement
    secondary: tuple[Requirement, ...] = ()


@dataclass(frozen=True, slots=True)
class AllocationIn:
    allocation_id: str
    employee_id: str
    project_id: str
    role_id: str
    start_date: date
    end_date: date
    hours_per_week: float
    allocation_type: str
    status: str


@dataclass(frozen=True, slots=True)
class ActualIn:
    project_id: str
    role_id: str
    week_start_date: date
    actual_hours: float


@dataclass(frozen=True)
class AnalysisInputs:
    roles: tuple[RoleIn, ...] = ()
    skills: tuple[SkillIn, ...] = ()
    employees: tuple[EmployeeIn, ...] = ()
    skill_versions: tuple[SkillVersionIn, ...] = ()
    availability: tuple[AvailabilityIn, ...] = ()
    trainings: tuple[TrainingIn, ...] = ()
    projects: tuple[ProjectIn, ...] = ()
    demand: tuple[DemandLineIn, ...] = ()
    allocations: tuple[AllocationIn, ...] = ()
    actuals: tuple[ActualIn, ...] = ()

    @cached_property
    def role_by_id(self) -> dict[str, RoleIn]:
        return {r.role_id: r for r in self.roles}

    @cached_property
    def skill_by_id(self) -> dict[str, SkillIn]:
        return {s.skill_id: s for s in self.skills}

    @cached_property
    def employee_by_id(self) -> dict[str, EmployeeIn]:
        return {e.employee_id: e for e in self.employees}

    @cached_property
    def project_by_id(self) -> dict[str, ProjectIn]:
        return {p.project_id: p for p in self.projects}

    @cached_property
    def allocations_by_employee(self) -> dict[str, list[AllocationIn]]:
        out: dict[str, list[AllocationIn]] = defaultdict(list)
        for a in sorted(self.allocations, key=lambda a: a.allocation_id):
            out[a.employee_id].append(a)
        return out


@dataclass(frozen=True)
class AnalysisContext:
    """Dates and rule parameters shared by every engine of one run.

    * ``weeks``: Mondays of the capacity horizon (the whole planning horizon of the data).
    * ``window``: the analysis window for forecasts, gaps and recommendations - from the week
      containing ``as_of`` to the horizon end (BR-GAP-010). ``as_of`` is also the forecast
      origin (BR-FCT-004) and the date at which skill findings are evaluated (BR-SKL-004).
    """

    as_of: date
    horizon_start: date
    horizon_end: date
    rules: RulesConfig
    demand_basis: str = "PLANNED"
    forecast_method: str = "PLAN_RATIO"
    weeks: tuple[date, ...] = field(init=False)

    def __post_init__(self) -> None:
        first = monday_of(self.horizon_start)
        count = max(1, (self.horizon_end - first).days // 7 + 1)
        object.__setattr__(self, "weeks", tuple(first + timedelta(weeks=i) for i in range(count)))

    @property
    def period_start(self) -> date:
        return self.weeks[0]

    @property
    def period_end(self) -> date:
        return self.weeks[-1] + timedelta(days=6)

    @property
    def origin(self) -> date:
        return monday_of(self.as_of)

    @cached_property
    def window(self) -> tuple[date, ...]:
        return tuple(w for w in self.weeks if w >= self.origin)

    @cached_property
    def week_index(self) -> dict[date, int]:
        return {w: i for i, w in enumerate(self.weeks)}

    def param(self, rule_id: str, name: str) -> object:
        return self.rules.param(rule_id, name)

    def num(self, rule_id: str, name: str) -> float:
        value = self.rules.param(rule_id, name)
        assert isinstance(value, int | float)
        return float(value)

    def names(self, rule_id: str, name: str) -> frozenset[str]:
        value = self.rules.param(rule_id, name)
        assert isinstance(value, list)
        return frozenset(str(v) for v in value)

    @property
    def standard_hours(self) -> float:
        return self.num("BR-CAP-001", "standard_weekly_hours")

"""SQLAlchemy access for analysis runs: load inputs, store results, query results."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import ColumnElement, Select, case, func, insert, select
from sqlalchemy.orm import Session

from app.db.models import DatasetMetadata
from app.db.repository import Page, SqlAlchemyRepository, equal_to
from app.domain.enums import RunStatus
from app.domain.ids import EntityKind, run_scoped_id
from app.domain.units import quantize_hours
from app.modules.analytics.inputs import (
    ActualIn,
    AllocationIn,
    AnalysisInputs,
    AvailabilityIn,
    DemandLineIn,
    EmployeeIn,
    ProjectIn,
    Requirement,
    RoleIn,
    SkillIn,
    SkillVersionIn,
    TrainingIn,
)
from app.modules.analytics.models import (
    AnalysisRun,
    CapacitySnapshot,
    ExceptionFinding,
    ForecastResult,
    GapAnalysis,
    Recommendation,
    RecommendationGapLink,
)
from app.modules.analytics.pipeline import PipelineResult
from app.modules.analytics.schemas import (
    FindingQuery,
    ForecastQuery,
    GapQuery,
    RecommendationQuery,
    RunQuery,
)
from app.modules.projects.models import (
    Allocation,
    DemandActual,
    DemandPlan,
    DemandSkillRequirement,
    Project,
)
from app.modules.workforce.models import (
    Availability,
    Employee,
    EmployeeSkill,
    Role,
    Skill,
    Training,
)

BATCH = 5000


def _h(value: Any) -> Decimal:
    """Hours as Decimal(2) - numpy floats are converted to Python floats first."""
    return quantize_hours(float(value))


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return float(value)
    return value


class SqlAnalysisInputs:
    """Reads every source table once, as plain immutable records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _rows(self, columns: Sequence[Any], order: Any) -> list[dict[str, Any]]:
        result = self._session.execute(select(*columns).order_by(order))
        return [{k: _plain(v) for k, v in row._mapping.items()} for row in result]

    def dataset_metadata(self) -> dict[str, str]:
        rows = self._session.scalars(select(DatasetMetadata).order_by(DatasetMetadata.key))
        return {r.key: r.value for r in rows}

    def demand_week_range(self) -> tuple[date | None, date | None]:
        low, high = self._session.execute(
            select(func.min(DemandPlan.week_start_date), func.max(DemandPlan.week_start_date))
        ).one()
        return low, high

    def load(self) -> AnalysisInputs:
        e, es, av, tr = Employee, EmployeeSkill, Availability, Training
        requirements: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in self._rows(
            [
                DemandSkillRequirement.demand_id,
                DemandSkillRequirement.skill_id,
                DemandSkillRequirement.requirement_type,
                DemandSkillRequirement.min_proficiency,
            ],
            DemandSkillRequirement.skill_id,
        ):
            requirements[r["demand_id"]].append(r)
        demand = []
        for d in self._rows(
            [
                DemandPlan.demand_id,
                DemandPlan.project_id,
                DemandPlan.role_id,
                DemandPlan.week_start_date,
                DemandPlan.line_no,
                DemandPlan.required_hours,
                DemandPlan.status,
            ],
            DemandPlan.demand_id,
        ):
            reqs = requirements.get(d["demand_id"], [])
            primary = [r for r in reqs if r["requirement_type"] == "PRIMARY"]
            if not primary:
                continue  # malformed line (BR-DEM-001); cannot be analysed
            demand.append(
                DemandLineIn(
                    **d,
                    primary=Requirement(primary[0]["skill_id"], primary[0]["min_proficiency"]),
                    secondary=tuple(
                        Requirement(r["skill_id"], r["min_proficiency"])
                        for r in reqs
                        if r["requirement_type"] == "SECONDARY"
                    ),
                )
            )
        return AnalysisInputs(
            roles=tuple(
                RoleIn(**r)
                for r in self._rows([Role.role_id, Role.code, Role.role_family], Role.role_id)
            ),
            skills=tuple(
                SkillIn(**r)
                for r in self._rows(
                    [Skill.skill_id, Skill.code, Skill.requires_certification], Skill.skill_id
                )
            ),
            employees=tuple(
                EmployeeIn(**r)
                for r in self._rows(
                    [e.employee_id, e.role_id, e.hire_date, e.termination_date], e.employee_id
                )
            ),
            skill_versions=tuple(
                SkillVersionIn(**r)
                for r in self._rows(
                    [
                        es.employee_skill_id,
                        es.employee_id,
                        es.skill_id,
                        es.proficiency_level,
                        es.last_verified_date,
                        es.expiry_date,
                        es.recorded_status,
                        es.effective_from,
                        es.effective_to,
                    ],
                    es.employee_skill_id,
                )
            ),
            availability=tuple(
                AvailabilityIn(**r)
                for r in self._rows(
                    [
                        av.availability_id,
                        av.employee_id,
                        av.availability_type,
                        av.start_date,
                        av.end_date,
                        av.weekly_hours,
                        av.hours_per_day,
                        av.status,
                    ],
                    av.start_date,
                )
            ),
            trainings=tuple(
                TrainingIn(**r)
                for r in self._rows(
                    [
                        tr.training_id,
                        tr.employee_id,
                        tr.skill_id,
                        tr.start_date,
                        tr.end_date,
                        tr.hours_per_week,
                        tr.status,
                    ],
                    tr.training_id,
                )
            ),
            projects=tuple(
                ProjectIn(**r)
                for r in self._rows(
                    [
                        Project.project_id,
                        Project.priority,
                        Project.status,
                        Project.start_date,
                        Project.end_date,
                    ],
                    Project.project_id,
                )
            ),
            demand=tuple(demand),
            allocations=tuple(
                AllocationIn(**r)
                for r in self._rows(
                    [
                        Allocation.allocation_id,
                        Allocation.employee_id,
                        Allocation.project_id,
                        Allocation.role_id,
                        Allocation.start_date,
                        Allocation.end_date,
                        Allocation.hours_per_week,
                        Allocation.allocation_type,
                        Allocation.status,
                    ],
                    Allocation.allocation_id,
                )
            ),
            actuals=tuple(
                ActualIn(**r)
                for r in self._rows(
                    [
                        DemandActual.project_id,
                        DemandActual.role_id,
                        DemandActual.week_start_date,
                        DemandActual.actual_hours,
                    ],
                    DemandActual.week_start_date,
                )
            ),
        )


class SqlAnalysisWriter:
    """Stores every result of one run in the caller's transaction (bulk inserts)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _insert(self, model: type[Any], rows: list[dict[str, Any]]) -> None:
        for start in range(0, len(rows), BATCH):
            self._session.execute(insert(model), rows[start : start + BATCH])

    def write(self, run_id: str, result: PipelineResult) -> None:
        self._capacity(run_id, result)
        self._forecasts(run_id, result)
        gap_ids = self._gaps(run_id, result)
        self._recommendations(run_id, result, gap_ids)
        self._findings(run_id, result)

    def _capacity(self, run_id: str, result: PipelineResult) -> None:
        rows = []
        for employee_id, cap in sorted(result.capacity.items()):
            for i, week in enumerate(result.ctx.weeks):
                if cap.gross[i] <= 0 and cap.allocated[i] <= 0:
                    continue  # not employed and not allocated: nothing to report
                gross, leave = _h(cap.gross[i]), _h(cap.leave[i])
                training, allocated = (
                    _h(cap.training[i]),
                    _h(cap.allocated[i]),
                )
                net = gross - leave - training
                rows.append(
                    {
                        "run_id": run_id,
                        "employee_id": employee_id,
                        "week_start_date": week,
                        "gross_hours": gross,
                        "leave_hours": leave,
                        "training_hours": training,
                        "net_hours": net,
                        "allocated_hours": allocated,
                        "free_hours": net - allocated,
                        "utilization": (allocated / net).quantize(Decimal("0.0001"))
                        if net > 0
                        else None,
                        "risk_band": result.band(cap, i),
                    }
                )
        self._insert(CapacitySnapshot, rows)

    def _forecasts(self, run_id: str, result: PipelineResult) -> None:
        self._insert(
            ForecastResult,
            [
                {
                    "run_id": run_id,
                    "method": r.method,
                    "project_id": r.project_id,
                    "role_id": r.role_id,
                    "week_start_date": r.week_start_date,
                    "planned_hours": _h(r.planned_hours),
                    "forecast_hours": _h(r.forecast_hours),
                }
                for r in result.forecast.rows
            ],
        )

    def _gaps(self, run_id: str, result: PipelineResult) -> list[str]:
        rows, ids = [], []
        for seq, gap in enumerate(result.gaps.rows, start=1):
            gap_id = gap.gap_id = run_scoped_id(EntityKind.GAP, run_id, seq)
            ids.append(gap_id)
            demand = _h(gap.demand_hours)
            committed = min(_h(gap.committed_hours), demand)
            gap_hours = demand - committed
            parts = [
                min(_h(v), gap_hours)
                for v in (gap.reallocated_hours, gap.trained_hours, gap.hire_hours)
            ]
            overshoot = sum(parts, Decimal(0)) - gap_hours  # rounding of separate parts
            if overshoot > 0:
                largest = parts.index(max(parts))
                parts[largest] -= overshoot
            unresolved = gap_hours - sum(parts, Decimal(0))
            iso = gap.week_start_date.isocalendar()
            rows.append(
                {
                    "gap_id": gap_id,
                    "run_id": run_id,
                    "project_id": gap.project_id,
                    "role_id": gap.role_id,
                    "skill_id": gap.skill_id,
                    "iso_year": iso.year,
                    "iso_week": iso.week,
                    "week_start_date": gap.week_start_date,
                    "demand_hours": demand,
                    "committed_hours": committed,
                    "at_risk_hours": _h(gap.at_risk_hours),
                    "gap_hours": gap_hours,
                    "coverage_ratio": (committed / demand).quantize(Decimal("0.0001")),
                    "reallocated_hours": parts[0],
                    "trained_hours": parts[1],
                    "hire_hours": parts[2],
                    "unresolved_hours": unresolved,
                    "severity": result.severity(gap),
                    "source_demand_ids": gap.source_demand_ids,
                }
            )
        self._insert(GapAnalysis, rows)
        return ids

    def _recommendations(self, run_id: str, result: PipelineResult, gap_ids: list[str]) -> None:
        recs, links = [], []
        for rank, rec in enumerate(result.recommendations, start=1):
            rec_id = run_scoped_id(EntityKind.RECOMMENDATION, run_id, rank)
            recs.append(
                {
                    "recommendation_id": rec_id,
                    "run_id": run_id,
                    "recommendation_type": rec.recommendation_type,
                    "hire_type": rec.hire_type,
                    "role_id": rec.role_id,
                    "skill_id": rec.skill_id,
                    "employee_id": rec.employee_id,
                    "project_id": rec.project_id,
                    "period_start": rec.period_start,
                    "period_end": rec.period_end,
                    "hours": _h(rec.hours),
                    "headcount": rec.headcount,
                    "rank": rank,
                    "strategy_name": rec.strategy_name,
                    "rule_ids": rec.rule_ids,
                    "explanation": rec.explanation,
                    "assumptions": rec.assumptions,
                    "source_refs": [
                        *rec.source_refs,
                        *({"type": "gap_analysis", "id": gap_ids[i]} for i in sorted(rec.links)),
                    ],
                    "status": "PROPOSED",
                }
            )
            links += [
                {
                    "recommendation_id": rec_id,
                    "gap_id": gap_ids[i],
                    "covered_hours": _h(hours),
                }
                for i, hours in sorted(rec.links.items())
                if _h(hours) > 0
            ]
        self._insert(Recommendation, recs)
        self._insert(RecommendationGapLink, links)

    def _findings(self, run_id: str, result: PipelineResult) -> None:
        self._insert(
            ExceptionFinding,
            [
                {
                    "finding_id": run_scoped_id(EntityKind.FINDING, run_id, seq),
                    "run_id": run_id,
                    "anomaly_type": f.anomaly_type,
                    "rule_id": f.rule_id,
                    "entity_type": f.entity_type,
                    "entity_id": f.entity_id,
                    "week_start_date": f.week_start_date,
                    "related_ids": list(f.related_ids),
                    "severity": f.severity,
                    "message": f.message,
                    "details": f.details,
                    "status": "OPEN",
                }
                for seq, f in enumerate(result.detection.findings, start=1)
            ],
        )


# ------------------------------------------------------------------ result queries
def _window(column: Any, date_from: date | None, date_to: date | None) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if date_from is not None:
        conditions.append(column >= date_from)
    if date_to is not None:
        conditions.append(column <= date_to)
    return conditions


class SqlRunRepository(SqlAlchemyRepository[AnalysisRun]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, AnalysisRun)

    def latest_succeeded(self) -> AnalysisRun | None:
        return self._session.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.status == RunStatus.SUCCEEDED)
            .order_by(AnalysisRun.started_at.desc(), AnalysisRun.run_id.desc())
            .limit(1)
        )

    def search(self, query: RunQuery) -> Page[AnalysisRun]:
        conditions = equal_to(AnalysisRun, {"status": query.status, "run_type": query.run_type})
        return self._paginate(conditions, page=query.page, page_size=query.page_size)


class SqlForecastRepository(SqlAlchemyRepository[ForecastResult]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ForecastResult)

    def _conditions(self, run_id: str, query: ForecastQuery) -> list[ColumnElement[bool]]:
        f = ForecastResult
        return [
            f.run_id == run_id,
            *equal_to(
                f,
                {"method": query.method, "project_id": query.project_id, "role_id": query.role_id},
            ),
            *_window(f.week_start_date, query.date_from, query.date_to),
        ]

    def search_in_run(self, run_id: str, query: ForecastQuery) -> Page[ForecastResult]:
        return self._paginate(
            self._conditions(run_id, query), page=query.page, page_size=query.page_size
        )

    def all_in_run(self, run_id: str, query: ForecastQuery) -> list[ForecastResult]:
        f = ForecastResult
        stmt = (
            select(f)
            .where(*self._conditions(run_id, query))
            .order_by(f.project_id, f.role_id, f.week_start_date)
        )
        return list(self._session.scalars(stmt))

    def skill_shares(self, run_id: str) -> dict[tuple[str, str, date], list[tuple[str, float]]]:
        """Planned hours per primary skill of each project-role-week (from the run's gaps)."""
        g = GapAnalysis
        rows = self._session.execute(
            select(g.project_id, g.role_id, g.week_start_date, g.skill_id, g.demand_hours)
            .where(g.run_id == run_id)
            .order_by(g.project_id, g.role_id, g.week_start_date, g.skill_id)
        )
        shares: dict[tuple[str, str, date], list[tuple[str, float]]] = defaultdict(list)
        for p, r, w, s, hours in rows:
            shares[(p, r, w)].append((s, float(hours)))
        return shares


class SqlCapacityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def weekly(
        self,
        run_id: str,
        *,
        role_id: str | None,
        employee_id: str | None,
        date_from: date | None,
        date_to: date | None,
        by_role: bool = False,
    ) -> list[dict[str, Any]]:
        c = CapacitySnapshot
        group: list[Any] = [c.week_start_date]
        if by_role:
            group.insert(0, Employee.role_id)
        stmt: Select[Any] = (
            select(
                *group,
                func.count().label("employee_weeks"),
                func.sum(c.gross_hours).label("gross"),
                func.sum(c.leave_hours).label("leave"),
                func.sum(c.training_hours).label("training"),
                func.sum(c.net_hours).label("net"),
                func.sum(c.allocated_hours).label("allocated"),
                func.sum(case((c.free_hours > 0, c.free_hours), else_=0)).label("available"),
                func.sum(case((c.free_hours < 0, -c.free_hours), else_=0)).label("overallocated"),
            )
            .join(Employee, Employee.employee_id == c.employee_id)
            .where(c.run_id == run_id, *_window(c.week_start_date, date_from, date_to))
            .group_by(*group)
            .order_by(*group)
        )
        if role_id is not None:
            stmt = stmt.where(Employee.role_id == role_id)
        if employee_id is not None:
            stmt = stmt.where(c.employee_id == employee_id)
        return [
            {k: _plain(v) for k, v in row._mapping.items()} for row in self._session.execute(stmt)
        ]

    def band_counts(
        self, run_id: str, *, role_id: str | None, date_from: date | None, date_to: date | None
    ) -> dict[str, int]:
        c = CapacitySnapshot
        stmt = (
            select(c.risk_band, func.count())
            .join(Employee, Employee.employee_id == c.employee_id)
            .where(c.run_id == run_id, *_window(c.week_start_date, date_from, date_to))
            .group_by(c.risk_band)
            .order_by(c.risk_band)
        )
        if role_id is not None:
            stmt = stmt.where(Employee.role_id == role_id)
        return {_plain(band): int(n) for band, n in self._session.execute(stmt)}


class SqlGapRepository(SqlAlchemyRepository[GapAnalysis]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, GapAnalysis)

    def _conditions(self, run_id: str, query: GapQuery) -> list[ColumnElement[bool]]:
        g = GapAnalysis
        conditions = [
            g.run_id == run_id,
            *equal_to(
                g,
                {
                    "project_id": query.project_id,
                    "role_id": query.role_id,
                    "skill_id": query.skill_id,
                    "severity": query.severity,
                },
            ),
            *_window(g.week_start_date, query.date_from, query.date_to),
        ]
        if query.only_gaps:
            conditions.append(g.gap_hours > 0)
        return conditions

    def search_in_run(self, run_id: str, query: GapQuery) -> Page[GapAnalysis]:
        return self._paginate(
            self._conditions(run_id, query), page=query.page, page_size=query.page_size
        )

    def all_in_run(self, run_id: str, query: GapQuery) -> list[GapAnalysis]:
        stmt = (
            select(GapAnalysis).where(*self._conditions(run_id, query)).order_by(GapAnalysis.gap_id)
        )
        return list(self._session.scalars(stmt))


class SqlFindingRepository(SqlAlchemyRepository[ExceptionFinding]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, ExceptionFinding)

    def search_in_run(self, run_id: str, query: FindingQuery) -> Page[ExceptionFinding]:
        f = ExceptionFinding
        conditions = [
            f.run_id == run_id,
            *equal_to(
                f,
                {
                    "anomaly_type": query.anomaly_type,
                    "severity": query.severity,
                    "entity_type": query.entity_type,
                    "entity_id": query.entity_id,
                    "status": query.status,
                },
            ),
            *_window(f.week_start_date, query.date_from, query.date_to),
        ]
        return self._paginate(conditions, page=query.page, page_size=query.page_size)

    def counts(self, run_id: str) -> dict[str, dict[str, int]]:
        f = ExceptionFinding
        out: dict[str, dict[str, int]] = defaultdict(dict)
        stmt = (
            select(f.anomaly_type, f.severity, func.count())
            .where(f.run_id == run_id)
            .group_by(f.anomaly_type, f.severity)
            .order_by(f.anomaly_type, f.severity)
        )
        for kind, severity, n in self._session.execute(stmt):
            out[_plain(kind)][_plain(severity)] = int(n)
        return dict(out)


class SqlRecommendationRepository(SqlAlchemyRepository[Recommendation]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Recommendation)

    def search_in_run(self, run_id: str, query: RecommendationQuery) -> Page[Recommendation]:
        r = Recommendation
        conditions = [
            r.run_id == run_id,
            *equal_to(
                r,
                {
                    "recommendation_type": query.recommendation_type,
                    "role_id": query.role_id,
                    "skill_id": query.skill_id,
                    "project_id": query.project_id,
                    "employee_id": query.employee_id,
                    "status": query.status,
                },
            ),
        ]
        return self._paginate(conditions, page=query.page, page_size=query.page_size)

    def links(self, recommendation_ids: Iterable[str]) -> dict[str, list[RecommendationGapLink]]:
        out: dict[str, list[RecommendationGapLink]] = defaultdict(list)
        stmt = (
            select(RecommendationGapLink)
            .where(RecommendationGapLink.recommendation_id.in_(list(recommendation_ids)))
            .order_by(RecommendationGapLink.recommendation_id, RecommendationGapLink.gap_id)
        )
        for link in self._session.scalars(stmt):
            out[link.recommendation_id].append(link)
        return out

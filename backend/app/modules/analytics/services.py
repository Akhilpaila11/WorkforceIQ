"""Analysis use-cases: run the pipeline and read its stored, traceable results."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.core.database import session_scope
from app.db.audit import SqlAlchemyAuditRecorder, snapshot
from app.db.ids import SqlIdAllocator
from app.db.repository import Page
from app.domain.calendar import iso_week_of, monday_of, month_of_week
from app.domain.enums import AuditAction, GapSeverity, RunStatus, RunType
from app.domain.errors import ConflictError, DomainValidationError, NotFoundError
from app.domain.ids import EntityKind
from app.domain.rules_config import RulesConfig
from app.modules.analytics.evaluation import GroundTruthSource, evaluate_detection
from app.modules.analytics.inputs import AnalysisContext
from app.modules.analytics.models import (
    AnalysisRun,
    ExceptionFinding,
    ForecastResult,
    GapAnalysis,
    Recommendation,
    RecommendationGapLink,
)
from app.modules.analytics.pipeline import AnalysisPipeline, PipelineResult, summarize
from app.modules.analytics.schemas import (
    CapacityGroupOut,
    CapacityQuery,
    CapacitySummaryOut,
    DashboardMetricsOut,
    FindingQuery,
    ForecastGroupOut,
    ForecastQuery,
    ForecastSummaryQuery,
    GapGroupOut,
    GapLinkOut,
    GapQuery,
    GapSummaryQuery,
    RecommendationOut,
    RecommendationQuery,
    RunCreate,
    RunQuery,
    WeekPointOut,
)
from app.modules.analytics.sql_repositories import SqlAnalysisInputs, SqlAnalysisWriter

logger = logging.getLogger("app.analytics")
STANDARD_HOURS = 40.0
SEVERITY_RANK = {s: i for i, s in enumerate(GapSeverity)}


# ------------------------------------------------------------------ run orchestration
class AnalysisRunService:
    """Creates a run, executes the pipeline, stores results; a failure is recorded as FAILED.

    The RUNNING row is committed first, results and the SUCCEEDED status in a second
    transaction, and a failure in a third - so a failed run never leaves partial results.
    """

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        rules: RulesConfig,
        ground_truth: GroundTruthSource,
        actor: str = "api",
        request_id: str | None = None,
    ) -> None:
        self._sessions = sessions
        self._rules = rules
        self._ground_truth = ground_truth
        self._actor = actor
        self._request_id = request_id

    def _context(
        self, cmd: RunCreate, meta: dict[str, str], demand: tuple[date | None, date | None]
    ) -> AnalysisContext:
        as_of = cmd.as_of_date or (
            date.fromisoformat(meta["as_of_date"]) if "as_of_date" in meta else None
        )
        if as_of is None:
            raise DomainValidationError(
                "as_of_date is required: the database has no dataset metadata"
            )
        start = date.fromisoformat(meta["horizon_start"]) if "horizon_start" in meta else None
        end = date.fromisoformat(meta["horizon_end"]) if "horizon_end" in meta else None
        start = start or demand[0] or monday_of(as_of)
        end = end or (
            demand[1] + timedelta(days=6) if demand[1] else monday_of(as_of) + timedelta(days=6)
        )
        if not start <= as_of <= end:
            raise DomainValidationError(
                f"as_of_date {as_of} is outside the planning horizon {start}..{end}",
                details={"horizon_start": start.isoformat(), "horizon_end": end.isoformat()},
            )
        return AnalysisContext(
            as_of=as_of,
            horizon_start=start,
            horizon_end=end,
            rules=self._rules,
            demand_basis=cmd.demand_basis,
            forecast_method=cmd.forecast_method.value,
        )

    def _audit(self, session: Session, run: AnalysisRun, action: AuditAction, before: Any) -> None:
        SqlAlchemyAuditRecorder(session).record(
            entity=run,
            action=action,
            before=before,
            actor=self._actor,
            request_id=self._request_id,
        )

    def start(self, cmd: RunCreate) -> AnalysisRun:
        with session_scope(self._sessions) as session:
            source = SqlAnalysisInputs(session)
            meta = source.dataset_metadata()
            ctx = self._context(cmd, meta, source.demand_week_range())
            run_id = SqlIdAllocator(session).next_id(EntityKind.ANALYSIS_RUN, year=ctx.as_of.year)
            run = AnalysisRun(
                run_id=run_id,
                run_type=RunType.FULL_PIPELINE,
                status=RunStatus.RUNNING,
                as_of_date=ctx.as_of,
                period_start=ctx.period_start,
                period_end=ctx.period_end,
                rules_version=self._rules.version,
                rules_sha256=self._rules.sha256,
                parameters={
                    "demand_basis": ctx.demand_basis,
                    "forecast_method": ctx.forecast_method,
                    "window_start": ctx.origin.isoformat(),
                    "dataset": meta,
                },
                summary=None,
                started_at=datetime.now(UTC),
                triggered_by=self._actor,
            )
            session.add(run)
            session.flush()
            self._audit(session, run, AuditAction.CREATE, None)
        try:
            with session_scope(self._sessions) as session:
                result = AnalysisPipeline(ctx, SqlAnalysisInputs(session).load()).run()
                summary = summarize(result)
                summary["detection_evaluation"] = self._evaluate(ctx, meta, result)
                SqlAnalysisWriter(session).write(run_id, result)
                self._finish(session, run_id, RunStatus.SUCCEEDED, summary=summary)
        except Exception as exc:
            logger.exception("analysis run %s failed", run_id)
            with session_scope(self._sessions) as session:
                self._finish(
                    session, run_id, RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}"
                )
            raise
        with self._sessions() as session:
            finished = session.get(AnalysisRun, run_id)
            assert finished is not None
            return finished

    def _finish(
        self,
        session: Session,
        run_id: str,
        status: RunStatus,
        *,
        summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        run = session.get(AnalysisRun, run_id)
        assert run is not None
        before = snapshot(run)
        run.status = status
        run.summary = summary
        run.error_message = error[:2000] if error else None
        run.finished_at = datetime.now(UTC)
        session.flush()
        self._audit(session, run, AuditAction.STATUS_CHANGE, before)

    def _evaluate(
        self, ctx: AnalysisContext, meta: dict[str, str], result: PipelineResult
    ) -> dict[str, Any]:
        """Runs after detection; ground truth never reaches the detectors."""
        if meta.get("as_of_date") != ctx.as_of.isoformat():
            return {
                "available": False,
                "reason": "as_of_date differs from the dataset's as_of_date; labels not comparable",
            }
        labels, source = self._ground_truth.load(meta)
        if labels is None:
            return {"available": False, "reason": source}
        evaluation = evaluate_detection(
            result.detection.findings, result.detection.populations, labels
        )
        evaluation["ground_truth"] = source
        return evaluation


# ------------------------------------------------------------------ reading results
class RunReader(Protocol):
    def get(self, entity_id: str) -> AnalysisRun | None: ...

    def latest_succeeded(self) -> AnalysisRun | None: ...

    def search(self, query: RunQuery) -> Page[AnalysisRun]: ...


class RunResolver:
    def __init__(self, runs: RunReader) -> None:
        self._runs = runs

    def get(self, run_id: str) -> AnalysisRun:
        run = self._runs.get(run_id)
        if run is None:
            raise NotFoundError("analysis_run", run_id)
        return run

    def list(self, query: RunQuery) -> Page[AnalysisRun]:
        return self._runs.search(query)

    def resolve(self, run_id: str | None) -> AnalysisRun:
        """The requested run, or the latest SUCCEEDED one; results need a SUCCEEDED run."""
        run = self._runs.get(run_id) if run_id else self._runs.latest_succeeded()
        if run is None:
            raise NotFoundError("analysis_run", run_id or "latest successful run")
        if run.status is not RunStatus.SUCCEEDED:
            raise ConflictError(
                f"run {run.run_id} is {run.status.value}; only SUCCEEDED runs have results",
                details={"run_id": run.run_id, "status": run.status.value},
            )
        return run


def paginate[T](items: list[T], page: int, page_size: int) -> Page[T]:
    start = (page - 1) * page_size
    return Page(
        items=items[start : start + page_size], page=page, page_size=page_size, total=len(items)
    )


def _period(week: date, period: str) -> tuple[str, date]:
    if period == "month":
        year, month = month_of_week(week)
        return f"{year:04d}-{month:02d}", date(year, month, 1)
    return iso_week_of(week).label, week


class ForecastReader(Protocol):
    def search_in_run(self, run_id: str, query: ForecastQuery) -> Page[ForecastResult]: ...

    def all_in_run(self, run_id: str, query: ForecastQuery) -> list[ForecastResult]: ...

    def skill_shares(self, run_id: str) -> dict[tuple[str, str, date], list[tuple[str, float]]]: ...


class ForecastService:
    def __init__(self, runs: RunResolver, forecasts: ForecastReader) -> None:
        self._runs = runs
        self._forecasts = forecasts

    def _with_method(self, run: AnalysisRun, query: ForecastQuery) -> ForecastQuery:
        method = query.method or run.parameters.get("forecast_method", "PLAN_RATIO")
        return query.model_copy(update={"method": method})

    def results(self, query: ForecastQuery) -> Page[ForecastResult]:
        run = self._runs.resolve(query.run_id)
        return self._forecasts.search_in_run(run.run_id, self._with_method(run, query))

    def summary(self, query: ForecastSummaryQuery) -> Page[ForecastGroupOut]:
        run = self._runs.resolve(query.run_id)
        rows = self._forecasts.all_in_run(run.run_id, self._with_method(run, query))
        split = query.group_by == "skill" or query.skill_id is not None
        shares = self._forecasts.skill_shares(run.run_id) if split else {}
        sums: dict[tuple[date, str | None], list[float]] = defaultdict(lambda: [0.0, 0.0])
        weeks: dict[tuple[date, str | None], set[date]] = defaultdict(set)
        labels: dict[date, str] = {}
        for row in rows:
            label, start = _period(row.week_start_date, query.period)
            labels[start] = label
            parts: Iterable[tuple[str | None, float]] = [(None, 1.0)]
            if split:
                skills = shares.get((row.project_id, row.role_id, row.week_start_date), [])
                total = sum(h for _, h in skills)
                parts = [(s, h / total) for s, h in skills] if total else [(None, 1.0)]
            for skill, share in parts:
                if query.skill_id is not None and skill != query.skill_id:
                    continue
                group = {
                    "total": None,
                    "project": row.project_id,
                    "role": row.role_id,
                    "skill": skill,
                }[query.group_by]
                bucket = sums[(start, group)]
                bucket[0] += float(row.planned_hours) * share
                bucket[1] += float(row.forecast_hours) * share
                weeks[(start, group)].add(row.week_start_date)
        items = [
            ForecastGroupOut(
                group=group,
                period=labels[start],
                period_start=start,
                weeks=len(weeks[(start, group)]),
                planned_hours=round(planned, 2),
                forecast_hours=round(forecast, 2),
                forecast_fte=round(forecast / (STANDARD_HOURS * len(weeks[(start, group)])), 3),
            )
            for (start, group), (planned, forecast) in sorted(
                sums.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
            )
        ]
        return paginate(items, query.page, query.page_size)


class CapacityReader(Protocol):
    def weekly(
        self,
        run_id: str,
        *,
        role_id: str | None,
        employee_id: str | None,
        date_from: date | None,
        date_to: date | None,
        by_role: bool = False,
    ) -> list[dict[str, Any]]: ...

    def band_counts(
        self, run_id: str, *, role_id: str | None, date_from: date | None, date_to: date | None
    ) -> dict[str, int]: ...


def capacity_group(group: str, rows: list[dict[str, Any]]) -> CapacityGroupOut:
    def total(key: str) -> float:
        return float(sum(r[key] or 0 for r in rows))

    weeks = len({r["week_start_date"] for r in rows}) or 1
    employee_weeks = int(sum(r["employee_weeks"] for r in rows))
    net, allocated = total("net"), total("allocated")
    fte = STANDARD_HOURS * weeks
    return CapacityGroupOut(
        group=group,
        weeks=weeks,
        employee_weeks=employee_weeks,
        avg_headcount=round(employee_weeks / weeks, 2),
        gross_hours=round(total("gross"), 2),
        leave_hours=round(total("leave"), 2),
        training_hours=round(total("training"), 2),
        net_hours=round(net, 2),
        allocated_hours=round(allocated, 2),
        available_hours=round(total("available"), 2),
        overallocated_hours=round(total("overallocated"), 2),
        part_time_and_partial_week_reduction_hours=round(
            STANDARD_HOURS * employee_weeks - total("gross"), 2
        ),
        utilization=round(allocated / net, 4) if net > 0 else None,
        fte_gross=round(total("gross") / fte, 2),
        fte_net=round(net / fte, 2),
        fte_allocated=round(allocated / fte, 2),
        fte_available=round(total("available") / fte, 2),
    )


class CapacityService:
    def __init__(self, runs: RunResolver, capacity: CapacityReader) -> None:
        self._runs = runs
        self._capacity = capacity

    def summary(self, query: CapacityQuery) -> CapacitySummaryOut:
        run = self._runs.resolve(query.run_id)
        rows = self._capacity.weekly(
            run.run_id,
            role_id=query.role_id,
            employee_id=query.employee_id,
            date_from=query.date_from,
            date_to=query.date_to,
            by_role=query.group_by == "role",
        )
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if query.group_by == "role":
                key = row["role_id"]
            elif query.group_by == "month":
                key = _period(row["week_start_date"], "month")[0]
            else:
                key = row["week_start_date"].isoformat()
            grouped[key].append(row)
        bands = self._capacity.band_counts(
            run.run_id, role_id=query.role_id, date_from=query.date_from, date_to=query.date_to
        )
        return CapacitySummaryOut(
            run_id=run.run_id,
            as_of_date=run.as_of_date,
            totals=capacity_group("total", rows) if rows else None,
            risk_bands=bands if query.employee_id is None else {},
            groups=[capacity_group(k, v) for k, v in sorted(grouped.items())],
        )


class GapReader(Protocol):
    def search_in_run(self, run_id: str, query: GapQuery) -> Page[GapAnalysis]: ...

    def all_in_run(self, run_id: str, query: GapQuery) -> list[GapAnalysis]: ...


def gap_group(group: str, rows: list[GapAnalysis]) -> GapGroupOut:
    def total(name: str) -> float:
        return float(sum(getattr(r, name) for r in rows))

    demand, committed, gap = total("demand_hours"), total("committed_hours"), total("gap_hours")
    weeks = len({r.week_start_date for r in rows}) or 1
    return GapGroupOut(
        group=group,
        rows=len(rows),
        weeks=weeks,
        demand_hours=round(demand, 2),
        committed_hours=round(committed, 2),
        at_risk_hours=round(total("at_risk_hours"), 2),
        gap_hours=round(gap, 2),
        coverage_ratio=round(committed / demand, 4) if demand else None,  # BR-GAP-007
        gap_fte=round(gap / (STANDARD_HOURS * weeks), 3),
        reallocated_hours=round(total("reallocated_hours"), 2),
        trained_hours=round(total("trained_hours"), 2),
        hire_hours=round(total("hire_hours"), 2),
        unresolved_hours=round(total("unresolved_hours"), 2),
        worst_severity=max((r.severity for r in rows), key=SEVERITY_RANK.__getitem__),
    )


GAP_KEYS: dict[str, Callable[[GapAnalysis], str]] = {
    "role": lambda r: r.role_id,
    "skill": lambda r: r.skill_id,
    "role_skill": lambda r: f"{r.role_id}|{r.skill_id}",
    "project": lambda r: r.project_id,
    "week": lambda r: r.week_start_date.isoformat(),
    "month": lambda r: _period(r.week_start_date, "month")[0],
}


class GapService:
    def __init__(self, runs: RunResolver, gaps: GapReader) -> None:
        self._runs = runs
        self._gaps = gaps

    def rows(self, query: GapQuery) -> Page[GapAnalysis]:
        return self._gaps.search_in_run(self._runs.resolve(query.run_id).run_id, query)

    def groups(self, run_id: str, query: GapQuery, group_by: str) -> list[GapGroupOut]:
        grouped: dict[str, list[GapAnalysis]] = defaultdict(list)
        for row in self._gaps.all_in_run(run_id, query):
            grouped[GAP_KEYS[group_by](row)].append(row)
        items = [gap_group(k, v) for k, v in grouped.items()]
        if group_by in ("week", "month"):
            return sorted(items, key=lambda g: g.group)
        return sorted(items, key=lambda g: (-g.gap_hours, g.group))

    def summary(self, query: GapSummaryQuery) -> Page[GapGroupOut]:
        run = self._runs.resolve(query.run_id)
        return paginate(self.groups(run.run_id, query, query.group_by), query.page, query.page_size)


class FindingReader(Protocol):
    def search_in_run(self, run_id: str, query: FindingQuery) -> Page[ExceptionFinding]: ...

    def counts(self, run_id: str) -> dict[str, dict[str, int]]: ...


class FindingService:
    def __init__(self, runs: RunResolver, findings: FindingReader) -> None:
        self._runs = runs
        self._findings = findings

    def list(self, query: FindingQuery) -> Page[ExceptionFinding]:
        return self._findings.search_in_run(self._runs.resolve(query.run_id).run_id, query)

    def evaluation(self, run_id: str | None) -> tuple[AnalysisRun, dict[str, Any]]:
        run = self._runs.resolve(run_id)
        return run, (run.summary or {}).get("detection_evaluation", {"available": False})


class RecommendationReader(Protocol):
    def get(self, entity_id: str) -> Recommendation | None: ...

    def search_in_run(self, run_id: str, query: RecommendationQuery) -> Page[Recommendation]: ...

    def links(
        self, recommendation_ids: Iterable[str]
    ) -> dict[str, list[RecommendationGapLink]]: ...


class RecommendationService:
    def __init__(self, runs: RunResolver, recommendations: RecommendationReader) -> None:
        self._runs = runs
        self._recs = recommendations

    def _out(self, recs: list[Recommendation]) -> list[RecommendationOut]:
        links = self._recs.links(r.recommendation_id for r in recs)
        return [
            RecommendationOut.model_validate(r).model_copy(
                update={
                    "gap_links": [
                        GapLinkOut.model_validate(link)
                        for link in links.get(r.recommendation_id, [])
                    ]
                }
            )
            for r in recs
        ]

    def list(self, query: RecommendationQuery) -> Page[RecommendationOut]:
        page = self._recs.search_in_run(self._runs.resolve(query.run_id).run_id, query)
        return Page(self._out(list(page.items)), page.page, page.page_size, page.total)

    def get(self, recommendation_id: str) -> RecommendationOut:
        rec = self._recs.get(recommendation_id)
        if rec is None:
            raise NotFoundError("recommendation", recommendation_id)
        return self._out([rec])[0]


class DashboardService:
    def __init__(
        self,
        runs: RunResolver,
        capacity: CapacityReader,
        gaps: GapService,
        forecasts: ForecastReader,
        findings: FindingReader,
    ) -> None:
        self._runs = runs
        self._capacity = capacity
        self._gaps = gaps
        self._forecasts = forecasts
        self._findings = findings

    def metrics(self, run_id: str | None) -> DashboardMetricsOut:
        run = self._runs.resolve(run_id)
        summary = run.summary or {}
        window_start = date.fromisoformat(run.parameters["window_start"])
        window = GapQuery(date_from=window_start, page_size=1)
        method = run.parameters.get("forecast_method", "PLAN_RATIO")
        forecast_rows = self._forecasts.all_in_run(
            run.run_id, ForecastQuery(method=method, date_from=window_start)
        )
        forecast_by_week: dict[date, float] = defaultdict(float)
        for f in forecast_rows:
            forecast_by_week[f.week_start_date] += float(f.forecast_hours)
        capacity_by_week = {
            r["week_start_date"]: r
            for r in self._capacity.weekly(
                run.run_id, role_id=None, employee_id=None, date_from=window_start, date_to=None
            )
        }
        gap_weeks = {g.group: g for g in self._gaps.groups(run.run_id, window, "week")}
        weekly = []
        for week in sorted(set(capacity_by_week) | set(forecast_by_week)):
            cap = capacity_by_week.get(week, {})
            g = gap_weeks.get(week.isoformat())
            net, allocated = float(cap.get("net") or 0), float(cap.get("allocated") or 0)
            weekly.append(
                WeekPointOut(
                    week_start_date=week,
                    demand_hours=g.demand_hours if g else 0.0,
                    forecast_hours=round(forecast_by_week.get(week, 0.0), 2),
                    committed_hours=g.committed_hours if g else 0.0,
                    gap_hours=g.gap_hours if g else 0.0,
                    net_hours=round(net, 2),
                    allocated_hours=round(allocated, 2),
                    utilization=round(allocated / net, 4) if net > 0 else None,
                )
            )
        top = self._gaps.groups(
            run.run_id, window.model_copy(update={"only_gaps": True}), "role_skill"
        )[:5]
        forecast_eval = summary.get("forecast", {}).get("evaluation", {})
        return DashboardMetricsOut(
            run_id=run.run_id,
            as_of_date=run.as_of_date,
            window=summary.get("window", {}),
            capacity=summary.get("capacity", {}),
            demand={
                **summary.get("demand", {}),
                "window_forecast_hours": round(sum(forecast_by_week.values()), 2),
                "forecast_method": method,
            },
            coverage=summary.get("gaps", {}),
            findings=self._findings.counts(run.run_id),
            recommendations=summary.get("recommendations", {}),
            forecast_accuracy={
                "available": forecast_eval.get("available", False),
                "reason": forecast_eval.get("reason"),
                "method": method,
                "metrics": forecast_eval.get("methods", {}).get(method),
                "all_methods": forecast_eval.get("methods", {}),
            },
            detection_evaluation=summary.get("detection_evaluation", {}),
            risk_bands=self._capacity.band_counts(
                run.run_id, role_id=None, date_from=window_start, date_to=None
            ),
            top_gaps=top,
            weekly=weekly,
        )

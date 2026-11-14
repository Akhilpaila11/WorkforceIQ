"""Demand forecasting (BR-FCT-001..005) - deterministic, explainable baselines, no ML.

* Grain: project x role x ISO week (BR-FCT-002) over the analysis window.
* Planned demand = counted, de-duplicated demand lines (BR-DEM-003/004).
* Methods (BR-FCT-003): NAIVE_PLAN, MOVING_AVERAGE, PLAN_RATIO (default).
* No look-ahead (BR-FCT-004): methods only see actuals of weeks before the forecast origin;
  hold-out actuals are read only by :class:`ForecastEvaluator`.
* Only projects whose status counts (BR-DEM-003) are forecast, and only for weeks that overlap
  the project's dates. No history is invented: where no actuals exist, metrics are reported as
  unavailable.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from app.domain.enums import ForecastMethod
from app.modules.analytics.inputs import ActualIn, AnalysisContext, AnalysisInputs, DemandLineIn

PRW = tuple[str, str, date]  # project, role, week
PR = tuple[str, str]


class HistoricalActuals:
    """Actuals strictly before the forecast origin (BR-FCT-004)."""

    def __init__(self, actuals: Iterable[ActualIn], origin: date) -> None:
        self.origin = origin
        self.hours: dict[PRW, float] = defaultdict(float)
        for a in actuals:
            if a.week_start_date < origin:
                self.hours[(a.project_id, a.role_id, a.week_start_date)] += a.actual_hours

    def weeks_before_origin(self, count: int, horizon_start: date) -> list[date]:
        weeks = [self.origin - timedelta(weeks=i) for i in range(1, count + 1)]
        return [w for w in weeks if w >= horizon_start]


@dataclass(frozen=True)
class ForecastRow:
    method: ForecastMethod
    project_id: str
    role_id: str
    week_start_date: date
    planned_hours: float
    forecast_hours: float


@dataclass
class ForecastOutput:
    rows: list[ForecastRow]
    ratio_sources: dict[str, int] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)

    def for_method(self, method: str) -> dict[PRW, float]:
        return {
            (r.project_id, r.role_id, r.week_start_date): r.forecast_hours
            for r in self.rows
            if r.method == method
        }

    def planned(self) -> dict[PRW, float]:
        return {(r.project_id, r.role_id, r.week_start_date): r.planned_hours for r in self.rows}


class ForecastStrategy(Protocol):
    method: ForecastMethod

    def forecast(self, grid: dict[PRW, float], history: HistoricalActuals) -> dict[PRW, float]:
        """``grid`` maps every forecast cell to its planned hours (0 when unplanned)."""
        ...


class NaivePlan:
    method = ForecastMethod.NAIVE_PLAN

    def forecast(self, grid: dict[PRW, float], history: HistoricalActuals) -> dict[PRW, float]:
        return dict(grid)


class MovingAverage:
    method = ForecastMethod.MOVING_AVERAGE

    def __init__(self, window: int, horizon_start: date) -> None:
        self._window = window
        self._horizon_start = horizon_start

    def forecast(self, grid: dict[PRW, float], history: HistoricalActuals) -> dict[PRW, float]:
        weeks = history.weeks_before_origin(self._window, self._horizon_start)
        means: dict[PR, float] = {}
        out: dict[PRW, float] = {}
        for p, r, w in grid:
            if (p, r) not in means:  # missing weeks count as 0 actual hours
                total = sum(history.hours.get((p, r, h), 0.0) for h in weeks)
                means[(p, r)] = total / len(weeks) if weeks else 0.0
            out[(p, r, w)] = means[(p, r)]
        return out


class PlanRatio:
    method = ForecastMethod.PLAN_RATIO

    def __init__(
        self,
        window: int,
        horizon_start: date,
        planned_history: dict[PRW, float],
        low: float,
        high: float,
        min_planned: float,
    ) -> None:
        self._window = window
        self._horizon_start = horizon_start
        self._planned = planned_history
        self._low, self._high, self._min_planned = low, high, min_planned
        self.sources: dict[str, int] = defaultdict(int)

    def _sums(
        self, history: HistoricalActuals, weeks: list[date]
    ) -> tuple[dict[Any, list[float]], dict[Any, list[float]], list[float]]:
        by_pr: dict[Any, list[float]] = defaultdict(lambda: [0.0, 0.0])
        by_role: dict[Any, list[float]] = defaultdict(lambda: [0.0, 0.0])
        total = [0.0, 0.0]
        window = set(weeks)
        cells = {k for k in self._planned if k[2] in window} | {
            k for k in history.hours if k[2] in window
        }
        for p, r, w in cells:
            actual = history.hours.get((p, r, w), 0.0)
            planned = self._planned.get((p, r, w), 0.0)
            for bucket in (by_pr[(p, r)], by_role[r], total):
                bucket[0] += actual
                bucket[1] += planned
        return by_pr, by_role, total

    def forecast(self, grid: dict[PRW, float], history: HistoricalActuals) -> dict[PRW, float]:
        weeks = history.weeks_before_origin(self._window, self._horizon_start)
        by_pr, by_role, total = self._sums(history, weeks)
        ratios: dict[PR, float] = {}
        out: dict[PRW, float] = {}
        for p, r, w in grid:
            if (p, r) not in ratios:
                ratio, source = 1.0, "DEFAULT"
                for name, (act, plan) in (
                    ("PROJECT_ROLE", by_pr.get((p, r), [0.0, 0.0])),
                    ("ROLE", by_role.get(r, [0.0, 0.0])),
                    ("GLOBAL", total),
                ):
                    if plan >= self._min_planned:
                        ratio, source = act / plan, name
                        break
                ratios[(p, r)] = min(self._high, max(self._low, ratio))
                self.sources[source] += 1
            out[(p, r, w)] = grid[(p, r, w)] * ratios[(p, r)]
        return out


def _metrics(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    """BR-FCT-005: MAE, WAPE, BIAS over (forecast, actual) pairs."""
    actual_total = sum(a for _, a in pairs)
    abs_error = sum(abs(f - a) for f, a in pairs)
    return {
        "points": len(pairs),
        "actual_hours": round(actual_total, 2),
        "forecast_hours": round(sum(f for f, _ in pairs), 2),
        "MAE": round(abs_error / len(pairs), 4) if pairs else None,
        "WAPE": round(abs_error / actual_total, 4) if actual_total > 0 else None,
        "BIAS": round(sum(f - a for f, a in pairs) / actual_total, 4) if actual_total > 0 else None,
    }


class ForecastEvaluator:
    """Accuracy on hold-out weeks (on/after the origin) that actually have actuals."""

    def __init__(self, actuals: Iterable[ActualIn], origin: date, window: tuple[date, ...]) -> None:
        self._hours: dict[PRW, float] = defaultdict(float)
        weeks = set(window)
        for a in actuals:
            if a.week_start_date >= origin and a.week_start_date in weeks:
                self._hours[(a.project_id, a.role_id, a.week_start_date)] += a.actual_hours
        self.weeks = sorted({k[2] for k in self._hours})

    def evaluate(self, forecasts: dict[str, dict[PRW, float]]) -> dict[str, Any]:
        if not self.weeks:
            return {
                "available": False,
                "reason": "no actual demand recorded on or after the forecast origin",
            }
        weeks = set(self.weeks)
        result: dict[str, Any] = {
            "available": True,
            "weeks": [w.isoformat() for w in self.weeks],
            "methods": {},
        }
        for method, cells in forecasts.items():
            keys = {k for k in cells if k[2] in weeks} | set(self._hours)
            prw = [(cells.get(k, 0.0), self._hours.get(k, 0.0)) for k in sorted(keys)]
            role_f: dict[tuple[str, date], float] = defaultdict(float)
            role_a: dict[tuple[str, date], float] = defaultdict(float)
            for p, r, w in keys:
                role_f[(r, w)] += cells.get((p, r, w), 0.0)
                role_a[(r, w)] += self._hours.get((p, r, w), 0.0)
            rw = [(role_f[k], role_a[k]) for k in sorted(set(role_f) | set(role_a))]
            result["methods"][method] = {
                "PROJECT_ROLE_WEEK": _metrics(prw),
                "ROLE_WEEK": _metrics(rw),
            }
        return result


class ForecastEngine:
    def __init__(self, ctx: AnalysisContext, inputs: AnalysisInputs) -> None:
        self._ctx = ctx
        self._inputs = inputs

    def _planned(self, lines: Iterable[DemandLineIn]) -> dict[PRW, float]:
        planned: dict[PRW, float] = defaultdict(float)
        for line in lines:
            planned[(line.project_id, line.role_id, line.week_start_date)] += line.required_hours
        return planned

    def run(self, kept_lines: tuple[DemandLineIn, ...]) -> ForecastOutput:
        ctx = self._ctx
        planned = self._planned(kept_lines)
        history = HistoricalActuals(self._inputs.actuals, ctx.origin)
        ma_window = int(ctx.num("BR-FCT-003", "moving_average_window_weeks"))
        project_statuses = ctx.names("BR-DEM-003", "counted_project_statuses")
        window = set(ctx.window)
        # Forecast cells: planned cells in the window, plus every window week of project-roles
        # with planned demand or recent actuals - restricted to counted projects' dates.
        recent = set(history.weeks_before_origin(ma_window, ctx.period_start))
        pairs = {(p, r) for p, r, w in planned if w in window} | {
            (p, r) for p, r, w in history.hours if w in recent
        }
        grid: dict[PRW, float] = {}
        for p, r in sorted(pairs):
            project = self._inputs.project_by_id.get(p)
            if project is None or project.status not in project_statuses:
                continue
            for w in ctx.window:
                if w <= project.end_date and w + timedelta(days=6) >= project.start_date:
                    grid[(p, r, w)] = planned.get((p, r, w), 0.0)
        ratio = PlanRatio(
            int(ctx.num("BR-FCT-003", "plan_ratio_window_weeks")),
            ctx.period_start,
            planned,
            ctx.num("BR-FCT-003", "plan_ratio_min"),
            ctx.num("BR-FCT-003", "plan_ratio_max"),
            ctx.num("BR-FCT-003", "plan_ratio_min_planned_hours"),
        )
        strategies: list[ForecastStrategy] = [
            NaivePlan(),
            MovingAverage(ma_window, ctx.period_start),
            ratio,
        ]
        enabled = ctx.names("BR-FCT-003", "available_methods")
        rows: list[ForecastRow] = []
        by_method: dict[str, dict[PRW, float]] = {}
        for strategy in strategies:
            if strategy.method.value not in enabled:
                continue
            values = strategy.forecast(grid, history)
            by_method[strategy.method.value] = values
            rows += [
                ForecastRow(strategy.method, p, r, w, grid[(p, r, w)], max(0.0, values[(p, r, w)]))
                for (p, r, w) in sorted(grid)
                if grid[(p, r, w)] > 0 or values[(p, r, w)] > 0
            ]
        evaluator = ForecastEvaluator(self._inputs.actuals, ctx.origin, ctx.window)
        return ForecastOutput(
            rows=rows, ratio_sources=dict(ratio.sources), evaluation=evaluator.evaluate(by_method)
        )

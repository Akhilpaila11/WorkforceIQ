"""The full analysis pipeline: capacity -> demand -> forecast -> gaps -> recommendations ->
detection. Pure computation; persistence is done by the service with the repositories.

Ground truth is not an input here. Detection evaluation is a separate step done by the service
after detection has finished (see ``evaluation.py``).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from app.domain.enums import RiskBand
from app.modules.analytics.capacity import EPS, CapacityCalculator, EmployeeCapacity, risk_band
from app.modules.analytics.demand import DemandSelection, DemandSelector
from app.modules.analytics.detection import (
    AnomalyDetectionEngine,
    ConflictDetector,
    DetectionOutput,
    DuplicateDemandDetector,
    ExpiredSkillDetector,
    OverallocationDetector,
    StaleSkillDetector,
)
from app.modules.analytics.forecasting import ForecastEngine, ForecastOutput
from app.modules.analytics.gaps import GapAnalyzer, GapOutput, GapRow, gap_severity
from app.modules.analytics.inputs import AnalysisContext, AnalysisInputs
from app.modules.analytics.recommendations import Rec, RecommendationEngine
from app.modules.analytics.skills import EligibilityPolicy, SkillBook

ASSUMPTIONS = [
    "A-P5-1 Forecast origin is the Monday of the as-of week; methods read only earlier actuals "
    "(BR-FCT-004). Only counted projects (BR-DEM-003) are forecast, for weeks inside the "
    "project dates; a week without an actual record counts as 0 h for MOVING_AVERAGE.",
    "A-P5-2 Allocated hours of an over-allocated employee count as committed only up to the "
    "employee's net hours that week (pro rata); the excess is at risk.",
    "A-P5-3 Allocations on a project/role/week without counted demand are unplanned staffing "
    "(BR-ALC-004) and never count as coverage.",
    "A-P5-4 A gap row aggregates the lines of one project, role, primary skill and week; its "
    "required proficiency is the highest of those lines.",
    "A-P5-5 A trained employee is assumed eligible after the lead time and covers later weeks "
    "of the same project/role/skill need, within free ledger hours.",
    "A-P5-6 A HIRE covers at most headcount x 40 h per week; anything left is unresolved.",
    "A-P5-7 Gap severity NONE (fully covered) is never escalated for CRITICAL projects.",
    "A-P5-8 Forecast roll-up to skills splits each project-role-week forecast by the run's "
    "planned hours per primary skill (BR-FCT-002).",
]


@dataclass
class PipelineResult:
    ctx: AnalysisContext
    capacity: dict[str, EmployeeCapacity]
    selection: DemandSelection
    forecast: ForecastOutput
    gaps: GapOutput
    recommendations: list[Rec]
    detection: DetectionOutput
    excess_hours: dict[str, float]

    def severity(self, row: GapRow) -> str:
        bands = {
            "low": self.ctx.num("BR-GAP-006", "low_min_coverage"),
            "medium": self.ctx.num("BR-GAP-006", "medium_min_coverage"),
            "high": self.ctx.num("BR-GAP-006", "high_min_coverage"),
        }
        escalate = self.ctx.names("BR-GAP-006", "escalate_for_priorities")
        return gap_severity(row.coverage_ratio, row.priority, bands, escalate).value

    def band(self, cap: EmployeeCapacity, i: int) -> RiskBand:
        return risk_band(
            float(cap.net[i]),
            float(cap.allocated[i]),
            self.ctx.num("BR-UTL-002", "under_utilized_below"),
            self.ctx.num("BR-UTL-002", "healthy_below"),
        )


class AnalysisPipeline:
    def __init__(self, ctx: AnalysisContext, inputs: AnalysisInputs) -> None:
        self._ctx = ctx
        self._inputs = inputs

    def run(self) -> PipelineResult:
        ctx, inputs = self._ctx, self._inputs
        calculator = CapacityCalculator(ctx)
        capacity = calculator.all(inputs)
        selector = DemandSelector(ctx, inputs)
        selection = selector.select()
        policy = EligibilityPolicy(ctx, inputs, SkillBook(inputs.skill_versions), capacity)
        forecast = ForecastEngine(ctx, inputs).run(selection.kept)
        scale = None
        if ctx.demand_basis == "FORECAST":  # BR-GAP-009
            chosen = forecast.for_method(ctx.forecast_method)
            planned = forecast.planned()
            scale = {k: chosen.get(k, 0.0) / v for k, v in planned.items() if v > 0}
        gaps = GapAnalyzer(
            ctx,
            inputs,
            selector,
            policy,
            capacity,
            calculator.weekdays,
            calculator.counted_allocation_statuses,
        ).run(selection.kept, scale)
        engine = RecommendationEngine(ctx, inputs, policy, capacity)
        recommendations = engine.run(gaps.rows)
        excess: dict[str, float] = defaultdict(float)
        for (employee_id, _), hours in engine.ledger.remaining().items():
            excess[inputs.employee_by_id[employee_id].role_id] += hours  # BR-GAP-008
        detection = AnomalyDetectionEngine(
            [
                OverallocationDetector(
                    ctx,
                    inputs,
                    capacity,
                    calculator.weekdays,
                    calculator.counted_allocation_statuses,
                ),
                ExpiredSkillDetector(ctx, inputs, policy.status_evaluator),
                DuplicateDemandDetector(selection),
                ConflictDetector(ctx, inputs, calculator.counted_allocation_statuses),
                StaleSkillDetector(ctx, inputs, policy.status_evaluator),
            ]
        ).run()
        return PipelineResult(
            ctx, capacity, selection, forecast, gaps, recommendations, detection, dict(excess)
        )


def _hours(value: float) -> float:
    return round(float(value), 2)


def capacity_totals(result: PipelineResult, weeks: tuple[date, ...]) -> dict[str, Any]:
    ctx = result.ctx
    index = [ctx.week_index[w] for w in weeks]
    totals = dict.fromkeys(("gross", "leave", "training", "net", "allocated"), 0.0)
    available = overallocated = 0.0
    bands: Counter[str] = Counter()
    bench, part_time, active = 0, set(), set()
    min_weeks = int(ctx.num("BR-UTL-005", "min_consecutive_weeks"))
    for employee_id, cap in result.capacity.items():
        if not index:
            break
        for name in totals:
            totals[name] += float(np.sum(getattr(cap, name)[index]))
        free = cap.free[index]
        available += float(np.sum(np.maximum(free, 0)))
        overallocated += float(np.sum(np.maximum(-free, 0)))
        streak = longest = 0
        for i in index:
            if not cap.active[i]:
                continue
            active.add(employee_id)
            if cap.part_time[i]:
                part_time.add(employee_id)
            band = result.band(cap, i)
            bands[band.value] += 1
            idle = band is RiskBand.UNDER_UTILIZED or (cap.net[i] > EPS and cap.allocated[i] <= EPS)
            streak = streak + 1 if idle else 0
            longest = max(longest, streak)
        bench += longest >= min_weeks  # BR-UTL-005
    n = max(1, len(weeks))
    standard = ctx.standard_hours
    return {
        "weeks": len(weeks),
        "active_employees": len(active),
        "part_time_employees": len(part_time),
        **{f"{k}_hours": _hours(v) for k, v in totals.items()},
        "available_hours": _hours(available),
        "overallocated_hours": _hours(overallocated),
        "utilization": round(totals["allocated"] / totals["net"], 4) if totals["net"] else None,
        "fte": {
            "gross": round(totals["gross"] / (standard * n), 2),
            "net": round(totals["net"] / (standard * n), 2),
            "allocated": round(totals["allocated"] / (standard * n), 2),
            "available": round(available / (standard * n), 2),
        },
        "risk_bands": dict(sorted(bands.items())),
        "bench_employees": bench,
    }


def summarize(result: PipelineResult) -> dict[str, Any]:
    ctx = result.ctx
    rows = result.gaps.rows
    demand = sum(r.demand_hours for r in rows)
    committed = sum(r.committed_hours for r in rows)
    recs_by_type: Counter[str] = Counter()
    rec_hours: dict[str, float] = defaultdict(float)
    for rec in result.recommendations:
        recs_by_type[rec.recommendation_type.value] += 1
        rec_hours[rec.recommendation_type.value] += rec.hours
    window_lines = [d for d in result.selection.kept if d.week_start_date in set(ctx.window)]
    return {
        "as_of_date": ctx.as_of.isoformat(),
        "window": {
            "start": ctx.window[0].isoformat() if ctx.window else None,
            "end": ctx.period_end.isoformat(),
            "weeks": len(ctx.window),
        },
        "capacity": capacity_totals(result, ctx.window),
        "demand": {
            "counted_lines": len(result.selection.counted),
            "duplicate_lines_excluded": len(result.selection.duplicates),
            "window_lines": len(window_lines),
            "window_planned_hours": _hours(sum(d.required_hours for d in window_lines)),
        },
        "forecast": {
            "default_method": ctx.forecast_method,
            "rows": len(result.forecast.rows),
            "plan_ratio_sources": result.forecast.ratio_sources,
            "evaluation": result.forecast.evaluation,
        },
        "gaps": {
            "rows": len(rows),
            "rows_with_gap": sum(1 for r in rows if r.gap_hours > EPS),
            "demand_hours": _hours(demand),
            "committed_hours": _hours(committed),
            "at_risk_hours": _hours(sum(r.at_risk_hours for r in rows)),
            "gap_hours": _hours(sum(r.gap_hours for r in rows)),
            "coverage_ratio": round(committed / demand, 4) if demand else None,
            "reallocated_hours": _hours(sum(r.reallocated_hours for r in rows)),
            "trained_hours": _hours(sum(r.trained_hours for r in rows)),
            "hire_hours": _hours(sum(r.hire_hours for r in rows)),
            "unresolved_hours": _hours(sum(r.residual_hours for r in rows)),
            "unplanned_allocated_hours": _hours(result.gaps.unplanned_allocated_hours),
            "by_severity": dict(sorted(Counter(result.severity(r) for r in rows).items())),
        },
        "recommendations": {
            "count": len(result.recommendations),
            "by_type": dict(sorted(recs_by_type.items())),
            "hours_by_type": {k: _hours(v) for k, v in sorted(rec_hours.items())},
            "hire_headcount": sum(r.headcount or 0 for r in result.recommendations),
        },
        "excess_capacity_hours_by_role": {
            k: _hours(v) for k, v in sorted(result.excess_hours.items())
        },
        "findings": {
            "count": len(result.detection.findings),
            "by_type": dict(
                sorted(Counter(f.anomaly_type.value for f in result.detection.findings).items())
            ),
            "populations": result.detection.populations,
        },
        "assumptions": ASSUMPTIONS,
    }

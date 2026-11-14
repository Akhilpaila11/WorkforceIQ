"""Recommendations: REALLOCATE -> TRAIN -> HIRE passes over all gaps (BR-REC-001..005).

A single :class:`CapacityLedger` holds every employee-week's free hours (BR-GAP-004). Every
reallocation and training debits it, so an hour is never offered to two competing demands.
Each strategy may only reduce a gap's *residual* hours; whatever is left is unresolved.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from app.domain.calendar import iso_week_of
from app.domain.enums import EffectiveSkillStatus, HireType, RecommendationType
from app.modules.analytics.capacity import EPS, EmployeeCapacity
from app.modules.analytics.gaps import MIN_HOURS, GapRow
from app.modules.analytics.inputs import AnalysisContext, AnalysisInputs
from app.modules.analytics.skills import EligibilityPolicy


class CapacityLedger:
    """Free hours per employee-week, never below zero (BR-GAP-004)."""

    def __init__(self, ctx: AnalysisContext, capacity: dict[str, EmployeeCapacity]) -> None:
        self._free: dict[tuple[str, date], float] = {}
        for employee_id, cap in capacity.items():
            for week in ctx.window:
                i = ctx.week_index[week]
                free = float(cap.free[i])
                if free > EPS and cap.active[i]:
                    self._free[(employee_id, week)] = free

    def free(self, employee_id: str, week: date) -> float:
        return self._free.get((employee_id, week), 0.0)

    def debit(self, employee_id: str, week: date, hours: float) -> None:
        left = self.free(employee_id, week) - hours
        if left < -EPS:
            raise ValueError(f"ledger overdraft for {employee_id} in {week}")
        self._free[(employee_id, week)] = max(0.0, left)

    def remaining(self) -> dict[tuple[str, date], float]:
        return {k: v for k, v in self._free.items() if v > EPS}


@dataclass
class Rec:
    recommendation_type: RecommendationType
    strategy_name: str
    role_id: str
    skill_id: str
    period_start: date
    period_end: date
    hours: float
    rule_ids: list[str]
    explanation: str
    assumptions: dict[str, Any]
    source_refs: list[dict[str, str]]
    links: dict[int, float]  # index of the gap row -> covered hours
    employee_id: str | None = None
    project_id: str | None = None
    hire_type: HireType | None = None
    headcount: int | None = None


def week_label(day: date) -> str:
    return iso_week_of(day).label


@dataclass
class _Piece:
    gap_index: int
    week: date
    hours: float


class RecommendationStrategy(Protocol):
    name: str

    def apply(self, gaps: list[GapRow]) -> list[Rec]: ...


@dataclass
class _Shared:
    ctx: AnalysisContext
    inputs: AnalysisInputs
    policy: EligibilityPolicy
    ledger: CapacityLedger
    trained: set[str] = field(default_factory=set)


class ReallocateStrategy:
    """BR-REC-002: give residual gap hours to eligible employees with free ledger hours."""

    name = "ReallocateStrategy"

    def __init__(self, shared: _Shared) -> None:
        self._s = shared
        self._min_hours = shared.ctx.num("BR-REC-002", "min_hours_per_week")

    def apply(self, gaps: list[GapRow]) -> list[Rec]:
        s = self._s
        pieces: dict[tuple[str, str, str, str], list[_Piece]] = defaultdict(list)
        scores: dict[tuple[str, str, str, str], float] = {}
        for index, gap in enumerate(gaps):
            if gap.residual_hours <= EPS:
                continue
            candidates = []
            for employee_id in s.policy.book.holders(gap.skill_id):
                free = s.ledger.free(employee_id, gap.week_start_date)
                if free < self._min_hours:
                    continue
                result = s.policy.check(employee_id, gap.need, gap.week_start_date)
                if result.eligible and result.proficiency is not None:
                    score = s.policy.score(
                        employee_id, gap.need, gap.week_start_date, result.proficiency
                    )
                    candidates.append((-score, employee_id))
            for neg_score, employee_id in sorted(candidates):  # BR-SKL-007 order
                residual = gap.residual_hours
                if residual <= EPS:
                    break
                take = min(residual, s.ledger.free(employee_id, gap.week_start_date))
                s.ledger.debit(employee_id, gap.week_start_date, take)
                gap.reallocated_hours += take
                key = (employee_id, gap.project_id, gap.role_id, gap.skill_id)
                pieces[key].append(_Piece(index, gap.week_start_date, take))
                scores[key] = max(scores.get(key, 0.0), -neg_score)
        recs: list[Rec] = []
        for key in sorted(pieces, key=lambda k: (min(p.gap_index for p in pieces[k]), k)):
            for run in _consecutive(pieces[key]):
                recs.append(self._rec(key, run, gaps, scores[key]))
        return recs

    def _rec(
        self, key: tuple[str, str, str, str], run: list[_Piece], gaps: list[GapRow], score: float
    ) -> Rec:
        employee_id, project_id, role_id, skill_id = key
        hours = sum(p.hours for p in run)
        first, last = run[0].week, run[-1].week
        demand_ids = sorted({d for p in run for d in gaps[p.gap_index].source_demand_ids})
        skill = self._s.inputs.skill_by_id[skill_id].code
        employee = self._s.inputs.employee_by_id[employee_id]
        return Rec(
            recommendation_type=RecommendationType.REALLOCATE,
            strategy_name=self.name,
            role_id=role_id,
            skill_id=skill_id,
            employee_id=employee_id,
            project_id=project_id,
            period_start=first,
            period_end=last + timedelta(days=6),
            hours=hours,
            rule_ids=["BR-REC-001", "BR-REC-002", "BR-SKL-006", "BR-SKL-007", "BR-GAP-004"],
            explanation=(
                f"Reallocate {employee_id} to {project_id} for {hours:.2f} h "
                f"({week_label(first)}..{week_label(last)}): eligible for {skill} "
                f"(BR-SKL-006, match score {score:.0f}) with free hours left after existing "
                f"allocations, leave and training; hours are debited from the capacity ledger "
                f"so they are not offered to another demand (BR-GAP-004)."
            ),
            assumptions={
                "min_hours_per_week": self._min_hours,
                "match_score": score,
                "employee_role_id": employee.role_id,
            },
            source_refs=[
                {"type": "employee", "id": employee_id},
                {"type": "project", "id": project_id},
                {"type": "skill", "id": skill_id},
                *({"type": "demand_plan", "id": d} for d in demand_ids),
            ],
            links=_links(run),
        )


class TrainStrategy:
    """BR-REC-003: recertify or upskill a near-eligible employee when lead time allows."""

    name = "TrainStrategy"

    def __init__(self, shared: _Shared) -> None:
        self._s = shared
        ctx = shared.ctx
        self._recert_weeks = int(ctx.num("BR-REC-003", "recertify_lead_weeks"))
        self._weeks_per_level = int(ctx.num("BR-REC-003", "upskill_lead_weeks_per_level"))
        self._max_levels = int(ctx.num("BR-REC-003", "max_levels_to_upskill"))
        self._training_hours = ctx.num("BR-REC-003", "training_hours_per_week")
        self._max_per_employee = int(ctx.num("BR-REC-003", "max_trainings_per_employee_per_run"))
        self._count: dict[str, int] = defaultdict(int)

    def _plan(self, employee_id: str, gap: GapRow) -> tuple[str, int, int] | None:
        """(kind, lead weeks, current level) when the employee is near-eligible."""
        s = self._s
        week = gap.week_start_date
        employee = s.inputs.employee_by_id[employee_id]
        if not s.policy.is_active(employee_id, week) or not s.policy.same_family(
            employee, gap.need
        ):
            return None
        result = s.policy.check(employee_id, gap.need, week)
        if result.eligible or result.proficiency is None or result.status is None:
            return None
        minimum = gap.need.primary.min_proficiency
        if result.proficiency >= minimum and result.status is not EffectiveSkillStatus.VALID:
            return "RECERTIFY", self._recert_weeks, result.proficiency
        levels = minimum - result.proficiency
        if result.status is EffectiveSkillStatus.VALID and 0 < levels <= self._max_levels:
            return "UPSKILL", self._weeks_per_level * levels, result.proficiency
        return None

    def apply(self, gaps: list[GapRow]) -> list[Rec]:
        s = self._s
        origin = s.ctx.origin
        recs: list[Rec] = []
        for gap in gaps:
            if gap.residual_hours <= EPS:
                continue
            options = []
            for employee_id in s.policy.book.holders(gap.skill_id):
                if self._count[employee_id] >= self._max_per_employee:
                    continue
                plan = self._plan(employee_id, gap)
                if plan is None:
                    continue
                lead = plan[1]
                ready = origin + timedelta(weeks=lead)
                training_weeks = [origin + timedelta(weeks=i) for i in range(lead)]
                if ready > gap.week_start_date or any(
                    s.ledger.free(employee_id, w) < self._training_hours - EPS
                    for w in training_weeks
                ):
                    continue
                free = s.ledger.free(employee_id, gap.week_start_date)
                if free <= EPS:
                    continue
                options.append((lead, -free, employee_id, plan, training_weeks))
            if options:
                lead, _, employee_id, plan, training_weeks = min(options)
                recs.append(self._train(employee_id, plan, training_weeks, gap, gaps))
        return recs

    def _train(
        self,
        employee_id: str,
        plan: tuple[str, int, int],
        training_weeks: list[date],
        gap: GapRow,
        gaps: list[GapRow],
    ) -> Rec:
        s = self._s
        kind, lead, level = plan
        for week in training_weeks:
            s.ledger.debit(employee_id, week, self._training_hours)
        self._count[employee_id] += 1
        s.trained.add(employee_id)
        pieces: list[_Piece] = []
        for index, other in enumerate(gaps):  # this gap and later weeks of the same need
            same = (other.project_id, other.role_id, other.skill_id) == (
                gap.project_id,
                gap.role_id,
                gap.skill_id,
            )
            if not same or other.week_start_date < gap.week_start_date:
                continue
            take = min(other.residual_hours, s.ledger.free(employee_id, other.week_start_date))
            if take > EPS and s.policy.is_active(employee_id, other.week_start_date):
                s.ledger.debit(employee_id, other.week_start_date, take)
                other.trained_hours += take
                pieces.append(_Piece(index, other.week_start_date, take))
        pieces.sort(key=lambda p: p.week)
        hours = sum(p.hours for p in pieces)
        skill = s.inputs.skill_by_id[gap.skill_id].code
        target = gap.need.primary.min_proficiency
        demand_ids = sorted({d for p in pieces for d in gaps[p.gap_index].source_demand_ids})
        reason = (
            f"holds {skill} at level {level} but it is not VALID (expired, stale or pending)"
            if kind == "RECERTIFY"
            else f"holds {skill} VALID at level {level}, below the required {target}"
        )
        return Rec(
            recommendation_type=RecommendationType.TRAIN,
            strategy_name=self.name,
            role_id=gap.role_id,
            skill_id=gap.skill_id,
            employee_id=employee_id,
            project_id=gap.project_id,
            period_start=pieces[0].week,
            period_end=pieces[-1].week + timedelta(days=6),
            hours=hours,
            rule_ids=["BR-REC-001", "BR-REC-003", "BR-SKL-002", "BR-SKL-006", "BR-GAP-004"],
            explanation=(
                f"Train {employee_id} ({kind.lower()}): {reason}. {lead} week(s) of training at "
                f"{self._training_hours:.0f} h/week from {week_label(training_weeks[0])} make them "
                f"eligible by {week_label(pieces[0].week)}; they then cover {hours:.2f} h of the "
                f"{skill} gap on {gap.project_id}. Training and project hours are debited from "
                f"the capacity ledger (BR-GAP-004)."
            ),
            assumptions={
                "training_kind": kind,
                "lead_weeks": lead,
                "current_level": level,
                "target_level": target,
                "training_hours_per_week": self._training_hours,
                "training_weeks": [w.isoformat() for w in training_weeks],
            },
            source_refs=[
                {"type": "employee", "id": employee_id},
                {"type": "project", "id": gap.project_id},
                {"type": "skill", "id": gap.skill_id},
                *({"type": "demand_plan", "id": d} for d in demand_ids),
            ],
            links=_links(pieces),
        )


class HireStrategy:
    """BR-REC-004: hire for sustained residual gaps of a role and primary skill."""

    name = "HireStrategy"

    def __init__(self, shared: _Shared) -> None:
        self._s = shared
        ctx = shared.ctx
        self._min_weeks = int(ctx.num("BR-REC-004", "min_gap_weeks"))
        self._min_avg = ctx.num("BR-REC-004", "min_avg_weekly_gap_hours")
        self._tolerance = ctx.num("BR-REC-004", "headcount_rounding_tolerance_fte")
        self._permanent_weeks = ctx.num("BR-REC-004", "permanent_min_remaining_project_weeks")
        self._standard = ctx.standard_hours

    def apply(self, gaps: list[GapRow]) -> list[Rec]:
        groups: dict[tuple[str, str], list[int]] = defaultdict(list)
        for index, gap in enumerate(gaps):
            if gap.residual_hours > EPS:
                groups[(gap.role_id, gap.skill_id)].append(index)
        recs = []
        for (role_id, skill_id), indexes in sorted(
            groups.items(), key=lambda kv: (min(gaps[i].order for i in kv[1]), kv[0])
        ):
            weekly: dict[date, float] = defaultdict(float)
            for i in indexes:
                weekly[gaps[i].week_start_date] += gaps[i].residual_hours
            if len(weekly) < self._min_weeks:
                continue
            avg = sum(weekly.values()) / len(weekly)
            if avg < self._min_avg:
                continue
            headcount = max(1, math.ceil(avg / self._standard - self._tolerance))
            recs.append(self._hire(role_id, skill_id, indexes, gaps, avg, headcount))
        return recs

    def _hire(
        self,
        role_id: str,
        skill_id: str,
        indexes: list[int],
        gaps: list[GapRow],
        avg: float,
        headcount: int,
    ) -> Rec:
        first_week = min(gaps[i].week_start_date for i in indexes)
        weights = [(gaps[i].residual_hours, gaps[i].project_id) for i in indexes]
        remaining = sum(
            h * max(0.0, (self._s.inputs.project_by_id[p].end_date - first_week).days / 7)
            for h, p in weights
        ) / sum(h for h, _ in weights)
        hire_type = HireType.PERMANENT if remaining >= self._permanent_weeks else HireType.CONTRACT
        capacity: dict[date, float] = defaultdict(lambda: headcount * self._standard)
        pieces = []
        for i in sorted(indexes, key=lambda i: gaps[i].order):
            gap = gaps[i]
            take = min(gap.residual_hours, capacity[gap.week_start_date])
            if take > EPS:
                capacity[gap.week_start_date] -= take
                gap.hire_hours += take
                pieces.append(_Piece(i, gap.week_start_date, take))
        hours = sum(p.hours for p in pieces)
        weeks = sorted({p.week for p in pieces})
        projects = sorted({gaps[p.gap_index].project_id for p in pieces})
        skill = self._s.inputs.skill_by_id[skill_id].code
        role = self._s.inputs.role_by_id[role_id].code
        return Rec(
            recommendation_type=RecommendationType.HIRE,
            strategy_name=self.name,
            role_id=role_id,
            skill_id=skill_id,
            project_id=projects[0] if len(projects) == 1 else None,
            hire_type=hire_type,
            headcount=headcount,
            period_start=weeks[0],
            period_end=weeks[-1] + timedelta(days=6),
            hours=hours,
            rule_ids=["BR-REC-001", "BR-REC-004", "BR-CAP-001", "BR-GAP-007"],
            explanation=(
                f"Hire {headcount} {hire_type.value.lower()} {role} with {skill}: after "
                f"reallocation and training, {len(weeks)} week(s) still lack on average "
                f"{avg:.1f} h/week ({avg / self._standard:.2f} FTE) across {len(projects)} "
                f"project(s); hours-weighted remaining project duration is {remaining:.1f} weeks "
                f"(PERMANENT if >= {self._permanent_weeks:.0f})."
            ),
            assumptions={
                "avg_weekly_residual_hours": round(avg, 2),
                "gap_weeks": len(weeks),
                "min_gap_weeks": self._min_weeks,
                "min_avg_weekly_gap_hours": self._min_avg,
                "headcount_rounding_tolerance_fte": self._tolerance,
                "remaining_project_weeks": round(remaining, 1),
            },
            source_refs=[
                {"type": "role", "id": role_id},
                {"type": "skill", "id": skill_id},
                *({"type": "project", "id": p} for p in projects),
            ],
            links=_links(pieces),
        )


def _consecutive(pieces: list[_Piece]) -> list[list[_Piece]]:
    """Merge pieces of consecutive weeks into runs (BR-REC-002)."""
    runs: list[list[_Piece]] = []
    for piece in sorted(pieces, key=lambda p: p.week):
        if runs and (piece.week - runs[-1][-1].week).days <= 7:
            runs[-1].append(piece)
        else:
            runs.append([piece])
    return runs


def _links(pieces: list[_Piece]) -> dict[int, float]:
    links: dict[int, float] = defaultdict(float)
    for p in pieces:
        links[p.gap_index] += p.hours
    return dict(links)


class RecommendationEngine:
    def __init__(
        self,
        ctx: AnalysisContext,
        inputs: AnalysisInputs,
        policy: EligibilityPolicy,
        capacity: dict[str, EmployeeCapacity],
    ) -> None:
        self.ledger = CapacityLedger(ctx, capacity)
        shared = _Shared(ctx, inputs, policy, self.ledger)
        available: dict[str, RecommendationStrategy] = {
            "REALLOCATE": ReallocateStrategy(shared),
            "TRAIN": TrainStrategy(shared),
            "HIRE": HireStrategy(shared),
        }
        order = ctx.param("BR-REC-001", "strategy_order")
        assert isinstance(order, list)
        self._strategies = [available[str(name)] for name in order]

    def run(self, gaps: list[GapRow]) -> list[Rec]:
        recs: list[Rec] = []
        for strategy in self._strategies:
            recs += [r for r in strategy.apply(gaps) if r.hours >= MIN_HOURS]
        return recs

"""Capacity and utilization engine (BR-CAP-001..009, BR-EMP-002, BR-UTL-001..003).

Per employee and ISO week of the horizon::

    gross     = scheduled hours on working days while employed      (BR-CAP-003/004)
    leave     = approved leave, capped at scheduled hours per day   (BR-CAP-005)
    training  = counted training, capped at scheduled - leave       (BR-CAP-006)
    net       = gross - leave - training (never negative)           (BR-CAP-007)
    allocated = counted allocations prorated by working days        (BR-CAP-008)
    free      = net - allocated (negative = over-allocated)         (BR-CAP-009)
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import numpy.typing as npt

from app.domain.enums import RiskBand
from app.modules.analytics.inputs import (
    AllocationIn,
    AnalysisContext,
    AnalysisInputs,
    AvailabilityIn,
    EmployeeIn,
    TrainingIn,
)

Vector = npt.NDArray[np.float64]
WORK_SCHEDULE = "WORK_SCHEDULE"
EPS = 1e-9


@dataclass(frozen=True)
class EmployeeCapacity:
    employee_id: str
    gross: Vector
    leave: Vector
    training: Vector
    allocated: Vector
    active: npt.NDArray[np.bool_]
    part_time: npt.NDArray[np.bool_]

    @property
    def net(self) -> Vector:
        net: Vector = np.maximum(self.gross - self.leave - self.training, 0.0)
        return net

    @property
    def free(self) -> Vector:
        free: Vector = self.net - self.allocated
        return free


def risk_band(net: float, allocated: float, under: float, healthy: float) -> RiskBand:
    """BR-UTL-002."""
    if net <= EPS:
        return RiskBand.OVERALLOCATED if allocated > EPS else RiskBand.UNAVAILABLE
    utilization = allocated / net
    if utilization < under:
        return RiskBand.UNDER_UTILIZED
    if utilization < healthy:
        return RiskBand.HEALTHY
    return RiskBand.HIGH if utilization <= 1.0 + EPS else RiskBand.OVERALLOCATED


def working_days_between(start: date, end: date, weekdays: frozenset[int]) -> int:
    """Working days in the inclusive range ``start..end`` (0 when the range is empty)."""
    if end < start:
        return 0
    days = (end - start).days + 1
    full_weeks, rest = divmod(days, 7)
    count = full_weeks * len(weekdays)
    first = start.isoweekday()
    count += sum(1 for i in range(rest) if (first - 1 + i) % 7 + 1 in weekdays)
    return count


def prorated_weeks(
    hours_per_week: float,
    start: date,
    end: date,
    weeks: Iterable[date],
    weekdays: frozenset[int],
) -> dict[date, float]:
    """BR-CAP-008: weekly hours x (working days of the week inside start..end) / working days."""
    out: dict[date, float] = {}
    per_day = hours_per_week / len(weekdays)
    for monday in weeks:
        sunday = monday + timedelta(days=6)
        if monday > end or sunday < start:
            continue
        days = working_days_between(max(start, monday), min(end, sunday), weekdays)
        if days:
            out[monday] = per_day * days
    return out


class CapacityCalculator:
    """Computes :class:`EmployeeCapacity` for every employee over the context's weeks."""

    def __init__(self, ctx: AnalysisContext) -> None:
        self._ctx = ctx
        self._weekdays = frozenset(int(d) for d in ctx.names("BR-CAP-002", "working_weekdays"))
        self._leave_statuses = ctx.names("BR-CAP-005", "counted_leave_statuses")
        self._training_on = bool(ctx.param("BR-CAP-006", "enabled"))
        self._training_statuses = ctx.names("BR-CAP-006", "counted_training_statuses")
        self._alloc_statuses = ctx.names("BR-CAP-008", "counted_allocation_statuses")
        self._standard = ctx.standard_hours
        days = len(ctx.weeks) * 7
        self._start = ctx.period_start
        self._days = days
        self._workday = np.array(
            [1.0 if (i % 7) + 1 in self._weekdays else 0.0 for i in range(days)]
        )

    @property
    def counted_allocation_statuses(self) -> frozenset[str]:
        return self._alloc_statuses

    @property
    def weekdays(self) -> frozenset[int]:
        return self._weekdays

    def _slice(self, start: date, end: date | None) -> slice | None:
        first = max(0, (start - self._start).days)
        last = self._days - 1 if end is None else min(self._days - 1, (end - self._start).days)
        return slice(first, last + 1) if first <= last else None

    def _weekly(self, daily: Vector) -> Vector:
        weekly: Vector = daily.reshape(-1, 7).sum(axis=1)
        return weekly

    def employee(
        self,
        employee: EmployeeIn,
        availability: Iterable[AvailabilityIn],
        trainings: Iterable[TrainingIn],
        allocations: Iterable[AllocationIn],
    ) -> EmployeeCapacity:
        per_workday = len(self._weekdays)
        employed = np.zeros(self._days)
        span = self._slice(employee.hire_date, employee.termination_date)
        if span:
            employed[span] = 1.0
        employed *= self._workday
        rate = np.zeros(self._days)  # weekly hours of the schedule in force on each day
        leave_raw = np.zeros(self._days)
        rows = list(availability)
        for row in rows:
            if row.availability_type == WORK_SCHEDULE and row.status != "CANCELLED":
                span = self._slice(row.start_date, row.end_date)
                if span and row.weekly_hours is not None:
                    rate[span] = row.weekly_hours
        scheduled = rate / per_workday * employed
        for row in rows:
            if row.availability_type == WORK_SCHEDULE or row.status not in self._leave_statuses:
                continue
            span = self._slice(row.start_date, row.end_date)
            if span:
                hours = scheduled[span] if row.hours_per_day is None else row.hours_per_day
                leave_raw[span] += hours * self._workday[span]
        leave = np.minimum(leave_raw, scheduled)
        train_raw = np.zeros(self._days)
        if self._training_on:
            for t in trainings:
                span = self._slice(t.start_date, t.end_date)
                if span and t.status in self._training_statuses:
                    train_raw[span] += t.hours_per_week / per_workday
        training = np.minimum(train_raw * self._workday, scheduled - leave)
        allocated = np.zeros(len(self._ctx.weeks))
        for a in allocations:
            if a.status in self._alloc_statuses:
                for monday, hours in prorated_weeks(
                    a.hours_per_week, a.start_date, a.end_date, self._ctx.weeks, self._weekdays
                ).items():
                    allocated[self._ctx.week_index[monday]] += hours
        part_time_days = (rate < self._standard - EPS) & (rate > 0) & (employed > 0)
        return EmployeeCapacity(
            employee_id=employee.employee_id,
            gross=self._weekly(scheduled),
            leave=self._weekly(leave),
            training=self._weekly(training),
            allocated=allocated,
            active=self._weekly(employed) > 0,  # BR-EMP-002
            part_time=part_time_days.reshape(-1, 7).any(axis=1),
        )

    def all(self, inputs: AnalysisInputs) -> dict[str, EmployeeCapacity]:
        avail: dict[str, list[AvailabilityIn]] = defaultdict(list)
        for row in inputs.availability:
            avail[row.employee_id].append(row)
        train: dict[str, list[TrainingIn]] = defaultdict(list)
        for t in inputs.trainings:
            train[t.employee_id].append(t)
        return {
            e.employee_id: self.employee(
                e,
                avail.get(e.employee_id, []),
                train.get(e.employee_id, []),
                inputs.allocations_by_employee.get(e.employee_id, []),
            )
            for e in sorted(inputs.employees, key=lambda e: e.employee_id)
        }

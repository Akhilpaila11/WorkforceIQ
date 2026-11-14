"""Weekly capacity of an employee computed from source records (BR-CAP-003..009).

This is the generator's own, independent implementation: it keeps the baseline valid,
computes ground-truth outcomes and the derived exports. The backend engines (Phase 5) are
written separately, so a bug in one cannot hide a bug in the other.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import numpy.typing as npt

from datagen.config import GeneratorConfig

Row = Mapping[str, Any]
FloatArray = npt.NDArray[np.float64]
_FAR_FUTURE = date(9999, 12, 31)


@dataclass(frozen=True)
class WeekCapacity:
    gross: FloatArray
    leave: FloatArray
    training: FloatArray
    allocated: FloatArray

    @property
    def net(self) -> FloatArray:
        net: FloatArray = self.gross - self.leave - self.training
        return net

    @property
    def free(self) -> FloatArray:
        free: FloatArray = self.net - self.allocated
        return free


class CapacityModel:
    def __init__(self, cfg: GeneratorConfig) -> None:
        self.start = cfg.horizon_start
        self.weeks = cfg.horizon_weeks
        self.days = self.weeks * 7
        weekdays = cfg.rule("BR-CAP-002", "working_weekdays")
        self.workday = np.array([1.0 if (i % 7) + 1 in weekdays else 0.0 for i in range(self.days)])
        self.days_per_week = len(weekdays)
        self.leave_statuses = set(cfg.rule("BR-CAP-005", "counted_leave_statuses"))
        self.training_statuses = set(cfg.rule("BR-CAP-006", "counted_training_statuses"))
        self.alloc_statuses = set(cfg.rule("BR-CAP-008", "counted_allocation_statuses"))
        self.tolerance = float(cfg.rule("BR-UTL-004", "tolerance_hours"))

    def span(self, start: date, end: date | None) -> slice | None:
        """Day slice of [start, end] clipped to the horizon (None if no overlap)."""
        s = max(0, (start - self.start).days)
        e = min(self.days - 1, ((end or _FAR_FUTURE) - self.start).days)
        return slice(s, e + 1) if s <= e else None

    def week_index(self, monday: date) -> int:
        return (monday - self.start).days // 7

    def _weekly(self, daily: FloatArray) -> FloatArray:
        weekly: FloatArray = daily.reshape(self.weeks, 7).sum(axis=1)
        return weekly

    def scheduled_daily(self, employee: Row, schedules: Iterable[Row]) -> FloatArray:
        employed = np.zeros(self.days)
        sl = self.span(employee["hire_date"], employee["termination_date"])
        if sl:
            employed[sl] = 1.0
        sched = np.zeros(self.days)
        for s in schedules:
            if s["availability_type"] == "WORK_SCHEDULE" and s["status"] != "CANCELLED":
                sl = self.span(s["start_date"], s["end_date"])
                if sl:
                    sched[sl] = float(s["weekly_hours"]) / self.days_per_week
        scheduled: FloatArray = sched * self.workday * employed
        return scheduled

    def compute(
        self,
        employee: Row,
        availability: Iterable[Row],
        trainings: Iterable[Row] = (),
        allocations: Iterable[Row] = (),
    ) -> WeekCapacity:
        availability = list(availability)
        sched = self.scheduled_daily(employee, availability)
        leave_raw = np.zeros(self.days)
        for a in availability:
            if a["availability_type"] == "WORK_SCHEDULE" or a["status"] not in self.leave_statuses:
                continue
            sl = self.span(a["start_date"], a["end_date"])
            if sl:
                hpd = a["hours_per_day"]
                leave_raw[sl] += sched[sl] if hpd is None else float(hpd) * self.workday[sl]
        leave = np.minimum(leave_raw, sched)
        train_raw = np.zeros(self.days)
        for t in trainings:
            if t["status"] in self.training_statuses:
                sl = self.span(t["start_date"], t["end_date"])
                if sl:
                    train_raw[sl] += float(t["hours_per_week"]) / self.days_per_week
        training = np.minimum(train_raw * self.workday, sched - leave)
        alloc = np.zeros(self.days)
        for x in allocations:
            if x["status"] in self.alloc_statuses:
                sl = self.span(x["start_date"], x["end_date"])
                if sl:
                    alloc[sl] += float(x["hours_per_week"]) / self.days_per_week
        alloc *= self.workday
        return WeekCapacity(
            gross=self._weekly(sched),
            leave=self._weekly(leave),
            training=self._weekly(training),
            allocated=self._weekly(alloc),
        )

    def prorated_hours(self, hours_per_week: float, start: date, end: date, monday: date) -> float:
        """Hours an allocation contributes to one week (BR-CAP-008)."""
        first = max(start, monday)
        last = min(end, monday + timedelta(days=6))
        days = sum(
            1 for i in range((last - first).days + 1) if (first + timedelta(days=i)).weekday() < 5
        )
        return hours_per_week * days / self.days_per_week if days > 0 else 0.0


def group_by[R: Mapping[str, Any]](rows: Iterable[R], key: str) -> dict[Any, list[R]]:
    out: dict[Any, list[R]] = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


def capacity_by_employee(
    cfg: GeneratorConfig, tables: Mapping[str, list[dict[str, Any]]]
) -> dict[str, WeekCapacity]:
    model = CapacityModel(cfg)
    avail = group_by(tables["availability"], "employee_id")
    train = group_by(tables.get("training", []), "employee_id")
    alloc = group_by(tables.get("allocation", []), "employee_id")
    return {
        e["employee_id"]: model.compute(
            e,
            avail.get(e["employee_id"], []),
            train.get(e["employee_id"], []),
            alloc.get(e["employee_id"], []),
        )
        for e in tables["employee"]
    }

"""ISO-8601 planning calendar (BR-CAP-002).

* A planning week runs Monday-Sunday and is named by ISO year + ISO week.
  Note: 2026-W01 starts on Monday 2025-12-29 (the ISO year differs from the calendar year).
* Working days are Monday-Friday by default.
* A week belongs to the calendar month of its Thursday.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import NamedTuple

from app.domain.errors import DomainValidationError

DEFAULT_WORKING_WEEKDAYS: tuple[int, ...] = (1, 2, 3, 4, 5)  # ISO weekday, 1 = Monday


class IsoWeek(NamedTuple):
    year: int
    week: int

    @property
    def label(self) -> str:
        """Compact label used inside demand IDs, e.g. ``2026W01``."""
        return f"{self.year:04d}W{self.week:02d}"

    @property
    def start(self) -> date:
        return week_start(self.year, self.week)


def iso_weeks_in_year(iso_year: int) -> int:
    """52 or 53. December 28 is always in the last ISO week of its year."""
    return date(iso_year, 12, 28).isocalendar().week


def week_start(iso_year: int, iso_week: int) -> date:
    """Monday of the given ISO week; raises for weeks that do not exist."""
    if not 1 <= iso_week <= iso_weeks_in_year(iso_year):
        raise DomainValidationError(f"{iso_year} has no ISO week {iso_week}")
    return date.fromisocalendar(iso_year, iso_week, 1)


def iso_week_of(day: date) -> IsoWeek:
    cal = day.isocalendar()
    return IsoWeek(cal.year, cal.week)


def is_week_start(day: date) -> bool:
    return day.isoweekday() == 1


def monday_of(day: date) -> date:
    return day - timedelta(days=day.isoweekday() - 1)


def working_days(
    week_monday: date, weekdays: Iterable[int] = DEFAULT_WORKING_WEEKDAYS
) -> list[date]:
    if not is_week_start(week_monday):
        raise DomainValidationError(f"{week_monday} is not a Monday")
    return [week_monday + timedelta(days=d - 1) for d in sorted(set(weekdays))]


def month_of_week(week_monday: date) -> tuple[int, int]:
    """(year, month) of the week's Thursday - each week belongs to exactly one month."""
    thursday = monday_of(week_monday) + timedelta(days=3)
    return thursday.year, thursday.month


def week_range(first_monday: date, count: int) -> list[date]:
    if not is_week_start(first_monday):
        raise DomainValidationError(f"{first_monday} is not a Monday")
    return [first_monday + timedelta(weeks=i) for i in range(count)]

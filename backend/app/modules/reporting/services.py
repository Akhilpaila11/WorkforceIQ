"""Dashboard summary use-case: assembles totals from a small statistics reader."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.modules.reporting.schemas import (
    AllocationTotals,
    AvailabilityTotals,
    Breakdown,
    DemandTotals,
    SkillTotals,
    SummaryOut,
)


class StatsReader(Protocol):
    def count(
        self, table: str, *, where_null: str | None = None, where_true: str | None = None
    ) -> int: ...

    def count_by(self, table: str, column: str) -> dict[str, int]: ...

    def total(self, table: str, column: str) -> float: ...

    def date_range(self, table: str, column: str) -> tuple[date | None, date | None]: ...

    def dataset_metadata(self) -> dict[str, str]: ...


class SummaryService:
    def __init__(self, stats: StatsReader) -> None:
        self._stats = stats

    def _breakdown(self, table: str) -> Breakdown:
        by_status = self._stats.count_by(table, "status")
        return Breakdown(total=sum(by_status.values()), by_status=by_status)

    def summary(self) -> SummaryOut:
        s = self._stats
        demand_status = s.count_by("demand_plan", "status")
        first, last = s.date_range("demand_plan", "week_start_date")
        alloc_status = s.count_by("allocation", "status")
        availability = s.count_by("availability", "availability_type")
        return SummaryOut(
            dataset=s.dataset_metadata(),
            employees=self._breakdown("employee"),
            roles=s.count("role"),
            skills=SkillTotals(
                total=s.count("skill"),
                requires_certification=s.count("skill", where_true="requires_certification"),
                employee_skill_versions=s.count("employee_skill"),
                current_employee_skills=s.count("employee_skill", where_null="effective_to"),
            ),
            projects=self._breakdown("project"),
            demand=DemandTotals(
                total=sum(demand_status.values()),
                by_status=demand_status,
                required_hours=s.total("demand_plan", "required_hours"),
                first_week=first,
                last_week=last,
            ),
            allocations=AllocationTotals(
                total=sum(alloc_status.values()),
                by_status=alloc_status,
                by_type=s.count_by("allocation", "allocation_type"),
            ),
            availability=AvailabilityTotals(total=sum(availability.values()), by_type=availability),
            training=self._breakdown("training"),
        )

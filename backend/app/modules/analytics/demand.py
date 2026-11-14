"""Which demand counts (BR-DEM-003) and duplicate demand (BR-DEM-004).

Shared by forecasting, gap analysis and detection so that every engine sees the same,
de-duplicated demand.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from app.modules.analytics.inputs import AnalysisContext, AnalysisInputs, DemandLineIn

PRIORITY_DEFAULT = 99


@dataclass(frozen=True)
class Duplicate:
    line: DemandLineIn
    kept: DemandLineIn


@dataclass(frozen=True)
class DemandSelection:
    counted: tuple[DemandLineIn, ...]  # BR-DEM-003, before de-duplication
    kept: tuple[DemandLineIn, ...]  # counted minus duplicates (used by every total)
    duplicates: tuple[Duplicate, ...]


class DemandSelector:
    def __init__(self, ctx: AnalysisContext, inputs: AnalysisInputs) -> None:
        self._ctx = ctx
        self._inputs = inputs
        ranks = ctx.param("BR-PRJ-002", "priority_rank")
        assert isinstance(ranks, dict)
        self._rank = {str(k): int(v) for k, v in ranks.items()}

    def priority_rank(self, project_id: str) -> int:
        project = self._inputs.project_by_id.get(project_id)
        return self._rank.get(project.priority, PRIORITY_DEFAULT) if project else PRIORITY_DEFAULT

    def order_key(self, line: DemandLineIn) -> tuple[int, date, str, int]:
        """BR-GAP-001: priority rank, week, project, line number."""
        return (
            self.priority_rank(line.project_id),
            line.week_start_date,
            line.project_id,
            line.line_no,
        )

    def select(self) -> DemandSelection:
        statuses = self._ctx.names("BR-DEM-003", "counted_demand_statuses")
        project_statuses = self._ctx.names("BR-DEM-003", "counted_project_statuses")
        projects = self._inputs.project_by_id
        counted = []
        for line in sorted(self._inputs.demand, key=lambda d: d.demand_id):
            p = projects.get(line.project_id)
            if (
                p is not None
                and line.status in statuses
                and p.status in project_statuses
                and line.week_start_date <= p.end_date
                and line.week_start_date + timedelta(days=6) >= p.start_date
            ):
                counted.append(line)
        groups: dict[tuple[str, date, str, str, int], list[DemandLineIn]] = defaultdict(list)
        for line in counted:
            key = (
                line.project_id,
                line.week_start_date,
                line.role_id,
                line.primary.skill_id,
                line.primary.min_proficiency,
            )
            groups[key].append(line)
        exclude = bool(self._ctx.param("BR-DEM-004", "exclude_duplicates_from_analysis"))
        duplicates: list[Duplicate] = []
        for group in groups.values():
            ordered = sorted(group, key=lambda d: d.line_no)  # keep = LOWEST_LINE_NO
            duplicates += [Duplicate(line, ordered[0]) for line in ordered[1:]]
        dropped = {d.line.demand_id for d in duplicates} if exclude else set()
        kept = tuple(line for line in counted if line.demand_id not in dropped)
        duplicates.sort(key=lambda d: d.line.demand_id)
        return DemandSelection(tuple(counted), kept, tuple(duplicates))

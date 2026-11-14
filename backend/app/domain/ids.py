"""Deterministic, immutable identifiers (docs/05-data-model.md section 5, BR-VAL-007).

Examples::

    format_id(EntityKind.EMPLOYEE, 1)              -> "EMP-000001"
    format_id(EntityKind.PROJECT, 1, year=2026)    -> "PRJ-2026-000001"
    demand_id("PRJ-2026-000001", 2026, 1, 1)       -> "DEM-PRJ-2026-000001-2026W01-01"
    run_scoped_id(EntityKind.GAP, "RUN-2026-000001", 42) -> "GAP-000001-000042"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.errors import DomainValidationError

SEQ_DIGITS = 6
MAX_SEQ = 10**SEQ_DIGITS - 1
MAX_DEMAND_LINE = 99


class EntityKind(StrEnum):
    EMPLOYEE = "EMPLOYEE"
    ROLE = "ROLE"
    SKILL = "SKILL"
    EMPLOYEE_SKILL = "EMPLOYEE_SKILL"
    PROJECT = "PROJECT"
    ALLOCATION = "ALLOCATION"
    AVAILABILITY = "AVAILABILITY"
    TRAINING = "TRAINING"
    ANALYSIS_RUN = "ANALYSIS_RUN"
    GAP = "GAP"
    RECOMMENDATION = "RECOMMENDATION"
    FINDING = "FINDING"
    GROUND_TRUTH = "GROUND_TRUTH"


@dataclass(frozen=True, slots=True)
class IdFormat:
    prefix: str
    has_year: bool = False
    run_scoped: bool = False

    @property
    def length(self) -> int:
        """Total length of a formatted ID (used by database CHECK constraints)."""
        extra = 5 if self.has_year else 0  # "YYYY-"
        extra += SEQ_DIGITS + 1 if self.run_scoped else 0  # "NNNNNN-"
        return len(self.prefix) + 1 + extra + SEQ_DIGITS

    @property
    def pattern(self) -> re.Pattern[str]:
        middle = r"\d{4}-" if self.has_year else ""
        middle += rf"\d{{{SEQ_DIGITS}}}-" if self.run_scoped else ""
        return re.compile(rf"^{self.prefix}-{middle}\d{{{SEQ_DIGITS}}}$")


ID_FORMATS: dict[EntityKind, IdFormat] = {
    EntityKind.EMPLOYEE: IdFormat("EMP"),
    EntityKind.ROLE: IdFormat("ROL"),
    EntityKind.SKILL: IdFormat("SKL"),
    EntityKind.EMPLOYEE_SKILL: IdFormat("ESK"),
    EntityKind.PROJECT: IdFormat("PRJ", has_year=True),
    EntityKind.ALLOCATION: IdFormat("ALLOC", has_year=True),
    EntityKind.AVAILABILITY: IdFormat("AVL", has_year=True),
    EntityKind.TRAINING: IdFormat("TRN", has_year=True),
    EntityKind.ANALYSIS_RUN: IdFormat("RUN", has_year=True),
    EntityKind.GAP: IdFormat("GAP", run_scoped=True),
    EntityKind.RECOMMENDATION: IdFormat("REC", run_scoped=True),
    EntityKind.FINDING: IdFormat("EXC", run_scoped=True),
    EntityKind.GROUND_TRUTH: IdFormat("GT"),
}

DEMAND_ID_PATTERN = re.compile(r"^DEM-(PRJ-\d{4}-\d{6})-(\d{4})W(\d{2})-(\d{2})$")
DEMAND_ID_LENGTH = 30


@dataclass(frozen=True, slots=True)
class DemandIdParts:
    project_id: str
    iso_year: int
    iso_week: int
    line_no: int


def _check_seq(seq: int) -> None:
    if not 1 <= seq <= MAX_SEQ:
        raise DomainValidationError(f"sequence {seq} outside 1..{MAX_SEQ}")


def format_id(kind: EntityKind, seq: int, *, year: int | None = None) -> str:
    """Format a global-sequence ID. ``year`` is required for year-segmented kinds."""
    fmt = ID_FORMATS[kind]
    if fmt.run_scoped:
        raise DomainValidationError(f"{kind} IDs are run-scoped; use run_scoped_id()")
    _check_seq(seq)
    if fmt.has_year:
        if year is None or not 1900 <= year <= 9999:
            raise DomainValidationError(f"{kind} IDs need a 4-digit year, got {year!r}")
        return f"{fmt.prefix}-{year:04d}-{seq:0{SEQ_DIGITS}d}"
    if year is not None:
        raise DomainValidationError(f"{kind} IDs have no year segment")
    return f"{fmt.prefix}-{seq:0{SEQ_DIGITS}d}"


def sequence_of(kind: EntityKind, value: str) -> int:
    """Return the trailing sequence number of a valid ID."""
    if not is_valid_id(kind, value):
        raise DomainValidationError(f"{value!r} is not a valid {kind} ID")
    return int(value[-SEQ_DIGITS:])


def is_valid_id(kind: EntityKind, value: str) -> bool:
    return bool(ID_FORMATS[kind].pattern.match(value))


def run_scoped_id(kind: EntityKind, run_id: str, seq: int) -> str:
    """IDs of analysis outputs: ``GAP|REC|EXC-<run sequence>-<sequence>``."""
    fmt = ID_FORMATS[kind]
    if not fmt.run_scoped:
        raise DomainValidationError(f"{kind} IDs are not run-scoped")
    _check_seq(seq)
    run_seq = sequence_of(EntityKind.ANALYSIS_RUN, run_id)
    return f"{fmt.prefix}-{run_seq:0{SEQ_DIGITS}d}-{seq:0{SEQ_DIGITS}d}"


def demand_id(project_id: str, iso_year: int, iso_week: int, line_no: int) -> str:
    """``DEM-<project_id>-<ISO year>W<ISO week>-<line>`` (BR-DEM-005)."""
    if not is_valid_id(EntityKind.PROJECT, project_id):
        raise DomainValidationError(f"{project_id!r} is not a valid project ID")
    if not 1 <= iso_week <= 53:
        raise DomainValidationError(f"ISO week {iso_week} outside 1..53")
    if not 1 <= line_no <= MAX_DEMAND_LINE:
        raise DomainValidationError(f"line number {line_no} outside 1..{MAX_DEMAND_LINE}")
    return f"DEM-{project_id}-{iso_year:04d}W{iso_week:02d}-{line_no:02d}"


def parse_demand_id(value: str) -> DemandIdParts:
    match = DEMAND_ID_PATTERN.match(value)
    if match is None:
        raise DomainValidationError(f"{value!r} is not a valid demand ID")
    project, year, week, line = match.groups()
    return DemandIdParts(project, int(year), int(week), int(line))

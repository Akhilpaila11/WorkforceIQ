"""Shared kernel: IDs, calendar, units, lifecycles, rules config."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain import calendar, units
from app.domain.enums import (
    AllocationStatus,
    DemandStatus,
    EmployeeStatus,
    ProjectStatus,
    RunStatus,
)
from app.domain.errors import DomainValidationError, InvalidStateTransition
from app.domain.ids import (
    DEMAND_ID_LENGTH,
    ID_FORMATS,
    EntityKind,
    demand_id,
    format_id,
    is_valid_id,
    parse_demand_id,
    run_scoped_id,
    sequence_of,
)
from app.domain.lifecycles import LIFECYCLES, assert_transition, is_terminal
from app.domain.rules_config import load_rules


# ------------------------------------------------------------------ IDs (BR-VAL-007)
@pytest.mark.parametrize(
    ("kind", "seq", "year", "expected"),
    [
        (EntityKind.EMPLOYEE, 1, None, "EMP-000001"),
        (EntityKind.SKILL, 300, None, "SKL-000300"),
        (EntityKind.PROJECT, 1, 2026, "PRJ-2026-000001"),
        (EntityKind.ALLOCATION, 1, 2026, "ALLOC-2026-000001"),
        (EntityKind.AVAILABILITY, 12, 2025, "AVL-2025-000012"),
        (EntityKind.ANALYSIS_RUN, 7, 2026, "RUN-2026-000007"),
        (EntityKind.GROUND_TRUTH, 1, None, "GT-000001"),
    ],
)
def test_format_id_matches_brief(kind: EntityKind, seq: int, year: int | None, expected: str):
    value = format_id(kind, seq, year=year)
    assert value == expected
    assert len(value) == ID_FORMATS[kind].length
    assert is_valid_id(kind, value)
    assert sequence_of(kind, value) == seq


def test_format_id_rejects_bad_input():
    with pytest.raises(DomainValidationError):
        format_id(EntityKind.EMPLOYEE, 0)
    with pytest.raises(DomainValidationError):
        format_id(EntityKind.EMPLOYEE, 1_000_000)
    with pytest.raises(DomainValidationError):
        format_id(EntityKind.PROJECT, 1)  # year required
    with pytest.raises(DomainValidationError):
        format_id(EntityKind.EMPLOYEE, 1, year=2026)  # no year allowed
    with pytest.raises(DomainValidationError):
        format_id(EntityKind.GAP, 1)  # run-scoped


def test_demand_id_round_trip_and_line_suffix():
    value = demand_id("PRJ-2026-000001", 2026, 1, 3)
    assert value == "DEM-PRJ-2026-000001-2026W01-03"
    assert len(value) == DEMAND_ID_LENGTH
    parts = parse_demand_id(value)
    assert (parts.project_id, parts.iso_year, parts.iso_week, parts.line_no) == (
        "PRJ-2026-000001",
        2026,
        1,
        3,
    )
    for bad in [("PRJ-1", 2026, 1, 1), ("PRJ-2026-000001", 2026, 54, 1)]:
        with pytest.raises(DomainValidationError):
            demand_id(*bad)
    with pytest.raises(DomainValidationError):
        demand_id("PRJ-2026-000001", 2026, 1, 100)
    with pytest.raises(DomainValidationError):
        parse_demand_id("DEM-PRJ-2026-000001-2026W1-01")


def test_run_scoped_ids():
    assert run_scoped_id(EntityKind.GAP, "RUN-2026-000001", 42) == "GAP-000001-000042"
    assert run_scoped_id(EntityKind.FINDING, "RUN-2026-000123", 1) == "EXC-000123-000001"
    with pytest.raises(DomainValidationError):
        run_scoped_id(EntityKind.EMPLOYEE, "RUN-2026-000001", 1)


# ------------------------------------------------------------------ calendar (BR-CAP-002)
def test_iso_calendar_edge_cases():
    assert calendar.week_start(2026, 1) == date(2025, 12, 29)  # A-03
    assert calendar.iso_week_of(date(2025, 12, 29)).label == "2026W01"
    assert calendar.iso_weeks_in_year(2026) == 53
    assert calendar.iso_weeks_in_year(2025) == 52
    with pytest.raises(DomainValidationError):
        calendar.week_start(2025, 53)
    assert calendar.month_of_week(date(2025, 12, 29)) == (2026, 1)  # Thursday = 2026-01-01
    assert calendar.month_of_week(date(2026, 3, 30)) == (2026, 4)  # Thursday = 2026-04-02
    days = calendar.working_days(date(2026, 3, 2))
    assert days[0] == date(2026, 3, 2) and days[-1] == date(2026, 3, 6) and len(days) == 5
    with pytest.raises(DomainValidationError):
        calendar.working_days(date(2026, 3, 3))
    assert calendar.monday_of(date(2026, 3, 8)) == date(2026, 3, 2)


# ------------------------------------------------------------------ units (BR-CAP-001)
def test_hours_and_fte():
    assert units.quantize_hours(Decimal("1.005")) == Decimal("1.01")  # half-up
    assert units.quantize_hours(0.1 + 0.2) == Decimal("0.30")
    assert units.hours_to_fte(60, weeks=2) == Decimal("0.750")
    assert units.fte_to_hours(Decimal("0.5")) == Decimal("20.00")
    with pytest.raises(ValueError, match="weeks"):
        units.hours_to_fte(10, weeks=0)


# ------------------------------------------------------------------ lifecycles
@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (EmployeeStatus.PENDING_START, EmployeeStatus.ACTIVE),
        (ProjectStatus.ON_HOLD, ProjectStatus.ACTIVE),
        (DemandStatus.SUBMITTED, DemandStatus.APPROVED),
        (AllocationStatus.CONFIRMED, AllocationStatus.COMPLETED),
        (RunStatus.RUNNING, RunStatus.FAILED),
    ],
)
def test_allowed_transitions(current, requested):
    assert_transition("x", current, requested)


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (EmployeeStatus.TERMINATED, EmployeeStatus.ACTIVE),
        (ProjectStatus.COMPLETED, ProjectStatus.ACTIVE),
        (DemandStatus.APPROVED, DemandStatus.DRAFT),
        (AllocationStatus.PROPOSED, AllocationStatus.COMPLETED),
        (DemandStatus.APPROVED, AllocationStatus.CANCELLED),  # different enum types
    ],
)
def test_invalid_transitions_raise(current, requested):
    with pytest.raises(InvalidStateTransition):
        assert_transition("x", current, requested)


def test_every_lifecycle_covers_all_states_and_has_a_terminal_state():
    for enum_cls, graph in LIFECYCLES.items():
        assert set(graph) == set(enum_cls), enum_cls
        assert any(is_terminal(s) for s in enum_cls), enum_cls
        for targets in graph.values():
            assert all(isinstance(t, enum_cls) for t in targets)


# ------------------------------------------------------------------ rules config
def test_load_rules(backend_dir: Path):
    rules = load_rules(backend_dir / "config" / "business_rules.toml")
    assert len(rules.rule_ids) == 68
    assert len(rules.sha256) == 64
    assert rules.param("BR-CAP-001", "standard_weekly_hours") == 40.0
    with pytest.raises(DomainValidationError):
        rules.rule("BR-XXX-999")
    with pytest.raises(DomainValidationError):
        rules.param("BR-CAP-001", "nope")
    with pytest.raises(TypeError):
        rules.rules["BR-CAP-001"]["standard_weekly_hours"] = 1  # type: ignore[index]

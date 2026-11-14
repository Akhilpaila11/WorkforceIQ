"""Database constraints on a migrated SQLite database (the same DDL as production)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.db.models import AuditEvent
from app.domain.enums import (
    AuditAction,
    AvailabilityStatus,
    AvailabilityType,
    EmployeeStatus,
    GapSeverity,
    RequirementType,
)
from app.domain.errors import ImmutableFieldError
from app.modules.analytics.models import GapAnalysis
from app.modules.projects.models import DemandPlan, Project
from app.modules.workforce.models import Employee, Role
from tests import factories as f

pytestmark = pytest.mark.integration


def expect_integrity_error(session: Session, *objects: object, match: str = "") -> None:
    session.add_all(objects)
    with pytest.raises(IntegrityError, match=match):
        session.flush()
    session.rollback()


@pytest.fixture
def seeded(session: Session) -> Session:
    f.seed_core(session)
    session.commit()
    return session


# ------------------------------------------------------------------ keys
def test_sqlite_enforces_foreign_keys(session: Session):
    assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_primary_key_uniqueness(seeded: Session):
    expect_integrity_error(seeded, f.role(code="OTHER", name="Other"), match="UNIQUE")


def test_unique_business_columns(seeded: Session):
    duplicate_email = f.employee(employee_id="EMP-000002")
    expect_integrity_error(seeded, duplicate_email, match="UNIQUE")


def test_foreign_key_integrity(seeded: Session):
    orphan = f.employee(employee_id="EMP-000002", email="b@example.com", role_id="ROL-000999")
    expect_integrity_error(seeded, orphan, match="FOREIGN KEY")


def test_restrict_delete_of_referenced_rows(seeded: Session):
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        seeded.execute(text("DELETE FROM role WHERE role_id = 'ROL-000001'"))
    seeded.rollback()


@pytest.mark.parametrize(
    "bad",
    [
        lambda: f.role(role_id="ROLE-01", code="X", name="X"),  # wrong prefix/length
        lambda: f.skill(skill_id="SKL-1", code="X", name="X"),
    ],
)
def test_id_format_checks(session: Session, bad: Callable[[], object]):
    expect_integrity_error(session, bad(), match="CHECK")


def test_demand_id_must_embed_its_project(seeded: Session):
    wrong = f.demand(demand_id="DEM-PRJ-2026-000002-2026W01-02", line_no=2)
    expect_integrity_error(seeded, wrong, match="CHECK")


# ------------------------------------------------------------------ enums
def test_enum_values_validated_by_database(seeded: Session):
    with pytest.raises(IntegrityError, match="CHECK"):
        seeded.execute(text("UPDATE employee SET status = 'RETIRED'"))
    seeded.rollback()


def test_enum_values_validated_in_python(session: Session):
    session.add(f.role(role_family="NOT_A_FAMILY"))
    with pytest.raises(StatementError):
        session.flush()
    session.rollback()


# ------------------------------------------------------------------ dates and ranges
@pytest.mark.parametrize(
    "make",
    [
        lambda: f.project(project_id="PRJ-2026-000002", end_date=date(2025, 1, 1)),
        lambda: f.allocation(end_date=date(2025, 1, 1)),
        lambda: f.employee_skill(effective_to=date(2020, 1, 1)),
        lambda: f.employee_skill(expiry_date=date(2025, 6, 2)),  # not after verification
    ],
)
def test_date_ordering(seeded: Session, make: Callable[[], object]):
    expect_integrity_error(seeded, make(), match="CHECK")


@pytest.mark.parametrize(
    "make",
    [
        lambda: f.allocation(hours_per_week=Decimal("0")),
        lambda: f.allocation(hours_per_week=Decimal("60.01")),
        lambda: f.demand(
            demand_id="DEM-PRJ-2026-000001-2026W01-02",
            line_no=2,
            headcount=1,
            required_hours=Decimal("41"),
        ),  # > headcount x 40
        lambda: f.employee_skill(proficiency_level=6),
        lambda: f.schedule(
            availability_id="AVL-2026-000002",
            start_date=date(2030, 1, 1),
            weekly_hours=Decimal("45"),
            status=AvailabilityStatus.CANCELLED,  # bypass the overlap trigger; test the CHECK
        ),
        lambda: f.schedule(
            availability_id="AVL-2026-000002",
            start_date=date(2030, 1, 1),
            availability_type=AvailabilityType.ANNUAL_LEAVE,
        ),  # needs end_date
    ],
)
def test_check_constraints_on_values(seeded: Session, make: Callable[[], object]):
    expect_integrity_error(seeded, make(), match="CHECK")


def test_terminated_employee_needs_termination_date(seeded: Session):
    emp = seeded.get(Employee, "EMP-000001")
    assert emp is not None
    emp.status = EmployeeStatus.TERMINATED
    with pytest.raises(IntegrityError, match="CHECK"):
        seeded.flush()
    seeded.rollback()


def test_certification_skill_requires_validity(session: Session):
    expect_integrity_error(session, f.skill(requires_certification=True), match="CHECK")


# ------------------------------------------------------------------ partial unique indexes
def test_only_one_current_skill_version(seeded: Session):
    seeded.add(f.employee_skill())
    seeded.flush()
    second_current = f.employee_skill(
        employee_skill_id="ESK-000002", effective_from=date(2026, 1, 5)
    )
    expect_integrity_error(seeded, second_current, match="UNIQUE")


def test_closed_versions_may_coexist(seeded: Session):
    seeded.add(f.employee_skill(effective_to=date(2026, 1, 4)))
    seeded.add(f.employee_skill(employee_skill_id="ESK-000002", effective_from=date(2026, 1, 5)))
    seeded.flush()


def test_only_one_primary_skill_per_demand_line(seeded: Session):
    seeded.add(f.skill(skill_id="SKL-000002", code="SQL", name="SQL"))
    seeded.flush()
    second_primary = f.requirement(skill_id="SKL-000002")
    expect_integrity_error(seeded, second_primary, match="UNIQUE")
    seeded.add(f.skill(skill_id="SKL-000002", code="SQL", name="SQL"))
    seeded.flush()
    seeded.add(f.requirement(skill_id="SKL-000002", requirement_type=RequirementType.SECONDARY))
    seeded.flush()


def test_duplicate_demand_business_key_is_allowed(seeded: Session):
    """Duplicates must be storable so detection can find them (A-15, A-17)."""
    seeded.add(f.demand(demand_id="DEM-PRJ-2026-000001-2026W01-02", line_no=2))
    seeded.flush()
    seeded.add(f.requirement(demand_id="DEM-PRJ-2026-000001-2026W01-02"))
    seeded.flush()
    assert len(seeded.scalars(select(DemandPlan)).all()) == 2


def test_demand_line_number_unique_per_project_week(seeded: Session):
    clash = f.demand(demand_id="DEM-PRJ-2026-000001-2026W01-01")
    seeded.expunge_all()
    seeded.add(clash)
    with pytest.raises(IntegrityError):
        seeded.flush()
    seeded.rollback()


# ------------------------------------------------------------------ triggers
def test_audit_event_is_append_only(seeded: Session):
    seeded.add(
        AuditEvent(
            actor="test",
            entity_type="role",
            entity_id="ROL-000001",
            action=AuditAction.CREATE,
            before_state=None,
            after_state={"role_id": "ROL-000001"},
        )
    )
    seeded.commit()
    for sql in ("UPDATE audit_event SET actor = 'mallory'", "DELETE FROM audit_event"):
        with pytest.raises(IntegrityError, match="append-only"):
            seeded.execute(text(sql))
        seeded.rollback()
    assert seeded.scalar(select(AuditEvent.actor)) == "test"


def test_audit_event_state_must_match_action(seeded: Session):
    bad = AuditEvent(
        actor="t",
        entity_type="role",
        entity_id="x",
        action=AuditAction.CREATE,
        before_state={"a": 1},
        after_state={"a": 2},
    )
    expect_integrity_error(seeded, bad, match="CHECK")


def test_work_schedules_cannot_overlap(seeded: Session):
    """Existing schedule is open-ended from 2024-01-08 (BR-VAL-009)."""
    overlapping = f.schedule(
        availability_id="AVL-2026-000002",
        start_date=date(2026, 3, 2),
        weekly_hours=Decimal("24"),
    )
    expect_integrity_error(seeded, overlapping, match="overlapping WORK_SCHEDULE")


def test_schedule_change_after_closing_previous_one(seeded: Session):
    from app.modules.workforce.models import Availability

    current = seeded.get(Availability, "AVL-2024-000001")
    assert current is not None
    current.end_date = date(2026, 3, 1)
    seeded.add(
        f.schedule(
            availability_id="AVL-2026-000002",
            start_date=date(2026, 3, 2),
            weekly_hours=Decimal("24"),
        )
    )
    seeded.flush()
    # leave may overlap a schedule; cancelled schedules are ignored by the trigger
    seeded.add_all(
        [
            f.schedule(
                availability_id="AVL-2026-000003",
                availability_type=AvailabilityType.ANNUAL_LEAVE,
                start_date=date(2026, 3, 9),
                end_date=date(2026, 3, 13),
                weekly_hours=None,
            ),
            f.schedule(
                availability_id="AVL-2026-000004",
                start_date=date(2026, 3, 2),
                weekly_hours=Decimal("40"),
                status=AvailabilityStatus.CANCELLED,
            ),
        ]
    )
    seeded.flush()


# ------------------------------------------------------------------ immutability (ORM guard)
def test_primary_key_is_immutable(seeded: Session):
    role = seeded.get(Role, "ROL-000001")
    assert role is not None
    role.role_id = "ROL-000002"
    with pytest.raises(ImmutableFieldError):
        seeded.flush()
    seeded.rollback()


def test_declared_immutable_columns(seeded: Session):
    line = seeded.get(DemandPlan, "DEM-PRJ-2026-000001-2026W01-01")
    assert line is not None
    line.iso_week = 2
    with pytest.raises(ImmutableFieldError, match="iso_week"):
        seeded.flush()
    seeded.rollback()


def test_mutable_columns_still_update(seeded: Session):
    project = seeded.get(Project, "PRJ-2026-000001")
    assert project is not None
    before = project.updated_at
    project.name = "Renamed"
    seeded.flush()
    assert project.updated_at >= before


# ------------------------------------------------------------------ types
def test_decimal_hours_are_exact(seeded: Session):
    seeded.add(f.allocation(hours_per_week=Decimal("12.345")))  # rounds half-up to 12.35
    seeded.commit()
    seeded.expire_all()
    value = seeded.scalar(text("SELECT hours_per_week FROM allocation"))
    from app.modules.projects.models import Allocation

    alloc = seeded.get(Allocation, "ALLOC-2026-000001")
    assert alloc is not None
    assert alloc.hours_per_week == Decimal("12.35")
    assert isinstance(alloc.hours_per_week, Decimal)
    assert value == pytest.approx(12.35)


def test_timestamps_are_utc_aware(seeded: Session):
    run = f.run(started_at=datetime(2026, 3, 2, 10, 30, tzinfo=timezone(timedelta(hours=1))))
    seeded.add(run)
    seeded.commit()
    seeded.expire_all()
    stored = seeded.get(type(run), "RUN-2026-000001")
    assert stored is not None
    assert stored.started_at == datetime(2026, 3, 2, 9, 30, tzinfo=UTC)
    assert stored.created_at.tzinfo is UTC


def test_naive_datetime_rejected(seeded: Session):
    seeded.add(f.run(started_at=datetime(2026, 3, 2, 9, 0)))
    with pytest.raises(StatementError, match="timezone-aware"):
        seeded.flush()
    seeded.rollback()


def test_gap_arithmetic_identity(seeded: Session):
    seeded.add(f.run())
    seeded.flush()
    common = {
        "run_id": "RUN-2026-000001",
        "project_id": "PRJ-2026-000001",
        "role_id": "ROL-000001",
        "skill_id": "SKL-000001",
        "iso_year": 2026,
        "iso_week": 10,
        "week_start_date": date(2026, 3, 2),
        "demand_hours": Decimal("80"),
        "committed_hours": Decimal("50"),
        "at_risk_hours": Decimal("0"),
        "coverage_ratio": Decimal("0.625"),
        "reallocated_hours": Decimal("10"),
        "trained_hours": Decimal("0"),
        "hire_hours": Decimal("20"),
        "unresolved_hours": Decimal("0"),
        "severity": GapSeverity.HIGH,
        "source_demand_ids": ["DEM-PRJ-2026-000001-2026W01-01"],
    }
    seeded.add(GapAnalysis(gap_id="GAP-000001-000001", gap_hours=Decimal("30"), **common))
    seeded.flush()
    wrong = GapAnalysis(
        gap_id="GAP-000001-000002",
        gap_hours=Decimal("31"),
        **(common | {"iso_week": 11, "week_start_date": date(2026, 3, 9)}),
    )
    expect_integrity_error(seeded, wrong, match="CHECK")


# ------------------------------------------------------------------ relationships / cardinality
def test_relationship_cardinality(seeded: Session):
    seeded.add_all(
        [
            f.employee_skill(effective_to=date(2026, 1, 4)),
            f.employee_skill(employee_skill_id="ESK-000002", effective_from=date(2026, 1, 5)),
            f.allocation(),
        ]
    )
    seeded.commit()
    seeded.expire_all()

    role = seeded.get(Role, "ROL-000001")
    emp = seeded.get(Employee, "EMP-000001")
    project = seeded.get(Project, "PRJ-2026-000001")
    line = seeded.get(DemandPlan, "DEM-PRJ-2026-000001-2026W01-01")
    assert role is not None and emp is not None and project is not None and line is not None

    assert [e.employee_id for e in role.employees] == ["EMP-000001"]  # Role 1:N Employee
    assert emp.role is role  # Employee N:1 Role
    assert [s.employee_skill_id for s in emp.skills] == ["ESK-000001", "ESK-000002"]  # versions
    assert [a.availability_type for a in emp.availability] == [AvailabilityType.WORK_SCHEDULE]
    assert [d.demand_id for d in project.demand_lines] == [line.demand_id]  # Project 1:N Demand
    assert [a.allocation_id for a in project.allocations] == ["ALLOC-2026-000001"]
    assert [r.requirement_type for r in line.skill_requirements] == [RequirementType.PRIMARY]

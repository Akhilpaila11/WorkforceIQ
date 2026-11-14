"""Synthetic data generator (Phase 3) - starter mode, checked from the exported files.

Expectations are recomputed here with plain Python from the CSV exports, independently of
the generator's own capacity model and checks.
"""

from __future__ import annotations

import csv
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.database import create_db_engine
from app.domain.ids import EntityKind, is_valid_id, sequence_of
from app.modules.projects.models import DemandPlan
from datagen.config import load_config
from datagen.loader import load_dataset
from datagen.pipeline import Dataset, compare_runs, run
from tests.conftest import sqlite_url

pytestmark = pytest.mark.integration
CFG = load_config("starter")
ALLOC_COUNTED = {"CONFIRMED", "COMPLETED"}


@pytest.fixture(scope="module")
def starter(tmp_path_factory: pytest.TempPathFactory) -> tuple[Dataset, dict[str, Any], Path]:
    out = tmp_path_factory.mktemp("generated")
    ds, manifest = run("starter", out_root=out)
    return ds, manifest, out / "starter"


@pytest.fixture(scope="module")
def data(starter: tuple[Dataset, dict[str, Any], Path]) -> dict[str, list[dict[str, str]]]:
    folder = starter[2]
    files = [
        *(folder / "csv").glob("*.csv"),
        *(folder / "derived").glob("*.csv"),
        folder / "ground_truth" / "ground_truth.csv",
    ]
    return {f.stem: list(csv.DictReader(f.open(encoding="utf-8"))) for f in files}


def d(text: str) -> date:
    return date.fromisoformat(text)


# ------------------------------------------------------------------ counts and validation
def test_configured_counts_and_validation(starter):
    ds, manifest, _ = starter
    assert ds.passed
    t = manifest["tables"]
    assert (t["employee"], t["skill"], t["project"], t["role"]) == (100, 30, 10, 10)
    for table in (
        "demand_plan",
        "allocation",
        "availability",
        "employee_skill",
        "training",
        "role_skill",
        "demand_skill_requirement",
        "demand_actual",
    ):
        assert t[table] > 0, table
    rule_ids = {c.rule_id for c in ds.checks}
    assert {
        "BR-VAL-001",
        "BR-VAL-002",
        "BR-VAL-003",
        "BR-VAL-004",
        "BR-VAL-005",
        "BR-VAL-006",
        "BR-VAL-008",
        "BR-VAL-009",
    } <= rule_ids
    baseline = next(c for c in ds.baseline_checks if c.name == "baseline contains no anomalies")
    assert baseline.passed


def test_keys_unique_and_foreign_keys_resolve(data):
    ids = {
        t: [r[f"{t}_id"] for r in data[t]]
        for t in ("employee", "skill", "project", "role", "allocation", "availability", "training")
    }
    ids["demand"] = [r["demand_id"] for r in data["demand_plan"]]
    ids["esk"] = [r["employee_skill_id"] for r in data["employee_skill"]]
    for name, values in ids.items():
        assert len(values) == len(set(values)), name
    sets = {k: set(v) for k, v in ids.items()}
    fks = [
        ("employee", "role_id", "role"),
        ("employee_skill", "employee_id", "employee"),
        ("employee_skill", "skill_id", "skill"),
        ("allocation", "employee_id", "employee"),
        ("allocation", "project_id", "project"),
        ("allocation", "role_id", "role"),
        ("availability", "employee_id", "employee"),
        ("demand_plan", "project_id", "project"),
        ("demand_skill_requirement", "demand_id", "demand"),
        ("demand_skill_requirement", "skill_id", "skill"),
        ("training", "outcome_employee_skill_id", "esk"),
        ("demand_actual", "role_id", "role"),
    ]
    for table, col, parent in fks:
        values = {r[col] for r in data[table] if r[col]}
        assert values <= sets[parent], f"{table}.{col}"


def test_enums_and_date_ordering(data):
    assert {r["status"] for r in data["allocation"]} <= {"PROPOSED", "CONFIRMED", "COMPLETED"}
    assert {r["allocation_type"] for r in data["allocation"]} == {"DEDICATED", "SHARED"}
    assert {r["recorded_status"] for r in data["employee_skill"]} <= {
        "CURRENT",
        "EXPIRED",
        "PENDING_VERIFICATION",
    }
    for table in ("allocation", "availability", "project", "training"):
        for r in data[table]:
            assert not r["end_date"] or d(r["end_date"]) >= d(r["start_date"]), table
    for r in data["employee_skill"]:
        assert not r["expiry_date"] or d(r["expiry_date"]) > d(r["last_verified_date"])
    for r in data["demand_plan"]:
        assert d(r["week_start_date"]).isoweekday() == 1
        assert CFG.horizon_start <= d(r["week_start_date"]) <= CFG.horizon_end


# ------------------------------------------------------------------ deterministic IDs
def test_deterministic_ids(data):
    emp = sorted(r["employee_id"] for r in data["employee"])
    assert emp == [f"EMP-{i:06d}" for i in range(1, 101)]
    assert sorted(r["skill_id"] for r in data["skill"]) == [f"SKL-{i:06d}" for i in range(1, 31)]
    projects = [r["project_id"] for r in data["project"]]
    assert "PRJ-2026-000001" in projects
    assert sorted(sequence_of(EntityKind.PROJECT, p) for p in projects) == list(range(1, 11))
    demand_ids = {r["demand_id"] for r in data["demand_plan"]}
    assert "DEM-PRJ-2026-000001-2026W01-01" in demand_ids
    lines = defaultdict(list)
    for r in data["demand_plan"]:
        assert r["demand_id"].startswith(f"DEM-{r['project_id']}-{int(r['iso_year']):04d}W")
        lines[(r["project_id"], r["week_start_date"])].append(int(r["line_no"]))
    assert all(sorted(v) == list(range(1, len(v) + 1)) for v in lines.values())
    allocs = [r["allocation_id"] for r in data["allocation"]]
    assert all(is_valid_id(EntityKind.ALLOCATION, a) for a in allocs)
    assert sorted(sequence_of(EntityKind.ALLOCATION, a) for a in allocs) == list(
        range(1, len(allocs) + 1)
    )


# ------------------------------------------------------------------ capacity arithmetic
def _independent_week(data, employee_id: str, monday: date) -> tuple[float, float]:
    """Net and allocated hours of one employee-week from raw CSV rows (BR-CAP-003..008)."""
    emp = next(r for r in data["employee"] if r["employee_id"] == employee_id)
    avail = [r for r in data["availability"] if r["employee_id"] == employee_id]
    trains = [
        r
        for r in data["training"]
        if r["employee_id"] == employee_id and r["status"] in ("PLANNED", "IN_PROGRESS")
    ]
    allocs = [
        r
        for r in data["allocation"]
        if r["employee_id"] == employee_id and r["status"] in ALLOC_COUNTED
    ]

    def within(day: date, r: dict[str, str]) -> bool:
        return d(r["start_date"]) <= day and (not r["end_date"] or day <= d(r["end_date"]))

    net = allocated = 0.0
    for i in range(5):
        day = monday + timedelta(days=i)
        employed = d(emp["hire_date"]) <= day and (
            not emp["termination_date"] or day <= d(emp["termination_date"])
        )
        sched = (
            sum(
                float(r["weekly_hours"]) / 5
                for r in avail
                if r["availability_type"] == "WORK_SCHEDULE" and within(day, r)
            )
            if employed
            else 0
        )
        leave = min(
            sched,
            sum(
                sched if not r["hours_per_day"] else float(r["hours_per_day"])
                for r in avail
                if r["availability_type"] != "WORK_SCHEDULE"
                and r["status"] == "APPROVED"
                and within(day, r)
            ),
        )
        training = min(
            sched - leave, sum(float(r["hours_per_week"]) / 5 for r in trains if within(day, r))
        )
        net += sched - leave - training
        allocated += sum(float(r["hours_per_week"]) / 5 for r in allocs if within(day, r))
    return net, allocated


def test_capacity_and_allocation_arithmetic(data):
    rows = data["capacity_weekly"]
    for r in rows:
        gross, leave, train, net, alloc, free = (
            float(r[k])
            for k in (
                "gross_hours",
                "leave_hours",
                "training_hours",
                "net_hours",
                "allocated_hours",
                "free_hours",
            )
        )
        assert abs(gross - leave - train - net) <= 0.011
        assert abs(net - alloc - free) <= 0.011
    sample = [r for r in rows if r["employee_id"] <= "EMP-000025"]
    for r in sample:
        net, alloc = _independent_week(data, r["employee_id"], d(r["week_start_date"]))
        assert abs(net - float(r["net_hours"])) <= 0.011, r
        assert abs(alloc - float(r["allocated_hours"])) <= 0.011, r
    util = [float(r["utilization"]) for r in rows if r["utilization"]]
    assert 0.2 < sum(util) / len(util) < 0.9


# ------------------------------------------------------------------ anomalies
def test_all_four_anomaly_types_hold_in_the_data(data):
    gt = data["ground_truth"]
    events = Counter()
    for kind in {r["anomaly_type"] for r in gt}:
        events[kind] = len({r["injection_event"] for r in gt if r["anomaly_type"] == kind})
    assert events == {
        "ALLOCATION_EXCEEDS_AVAILABILITY": 6,
        "EXPIRED_SKILL_TREATED_AS_CURRENT": 8,
        "DUPLICATE_DEMAND": 5,
        "OVERLAPPING_ALLOCATION_CONFLICT": 5,
    }
    cap = {(r["employee_id"], r["week_start_date"]): r for r in data["capacity_weekly"]}
    esk = {r["employee_skill_id"]: r for r in data["employee_skill"]}
    lines = {r["demand_id"]: r for r in data["demand_plan"]}
    primary = {
        r["demand_id"]: r
        for r in data["demand_skill_requirement"]
        if r["requirement_type"] == "PRIMARY"
    }
    allocs = {r["allocation_id"]: r for r in data["allocation"]}
    every_id = {v for rows in data.values() for r in rows for v in r.values()}
    for g in gt:
        assert all(s in every_id for s in g["source_record_ids"].split("|")), g["gt_id"]
        kind, key = g["anomaly_type"], g["evaluation_key"]
        if kind == "ALLOCATION_EXCEEDS_AVAILABILITY":
            row = cap[tuple(key.split("|"))]
            assert float(row["allocated_hours"]) > float(row["net_hours"]) + 0.01
        elif kind == "EXPIRED_SKILL_TREATED_AS_CURRENT":
            v = esk[key]
            assert v["recorded_status"] == "CURRENT" and not v["effective_to"]
            assert d(v["expiry_date"]) < CFG.as_of
        elif kind == "DUPLICATE_DEMAND":
            original = next(s for s in g["source_record_ids"].split("|") if s != key)
            a, b = lines[original], lines[key]
            assert (a["project_id"], a["week_start_date"], a["role_id"]) == (
                b["project_id"],
                b["week_start_date"],
                b["role_id"],
            )
            assert (primary[original]["skill_id"], primary[original]["min_proficiency"]) == (
                primary[key]["skill_id"],
                primary[key]["min_proficiency"],
            )
            assert int(b["line_no"]) > int(a["line_no"])
        else:
            a, b = (allocs[x] for x in key.split("|"))
            assert a["employee_id"] == b["employee_id"]
            assert d(a["start_date"]) <= d(b["end_date"]) and d(b["start_date"]) <= d(a["end_date"])
            assert "DEDICATED" in {a["allocation_type"], b["allocation_type"]}
            monday = d(g["week_start_date"])
            for wk in (monday, monday + timedelta(weeks=1)):  # pure exclusivity conflict
                row = cap[(a["employee_id"], wk.isoformat())]
                assert float(row["allocated_hours"]) <= float(row["net_hours"]) + 0.01


def test_injected_records_do_not_stand_out(data):
    """No label leakage through ID order or free text (A-30)."""
    gt_allocs = {
        s
        for g in data["ground_truth"]
        for s in g["source_record_ids"].split("|")
        if s.startswith("ALLOC-") and g["primary_record_type"] == "allocation"
    }
    seqs = sorted(
        sequence_of(EntityKind.ALLOCATION, a["allocation_id"]) for a in data["allocation"]
    )
    top = set(seqs[-len(gt_allocs) :])
    assert {sequence_of(EntityKind.ALLOCATION, a) for a in gt_allocs} != top
    assert {
        r["reason"] for r in data["availability"] if r["availability_type"] != "WORK_SCHEDULE"
    } == {""}
    assert {r["notes"] for r in data["allocation"]} == {""}


def test_ground_truth_is_separate_from_inputs(starter):
    _, _, folder = starter
    gt_files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("ground_truth*"))
    assert gt_files == [
        "ground_truth",
        "ground_truth/ground_truth.csv",
        "ground_truth/ground_truth.json",
    ]
    for sub in ("csv", "json", "sql", "derived"):
        for f in (folder / sub).iterdir():
            text = f.read_text(encoding="utf-8")
            for marker in ("anomaly_type", "ground_truth", "GT-0", "injection", "INJ-"):
                assert marker not in text, f"{f.name} contains {marker}"


# ------------------------------------------------------------------ reproducibility
def test_reproducible_with_same_seed_and_different_with_other_seed(starter, tmp_path):
    _, first, _ = starter
    _, second = run("starter", out_root=tmp_path / "a")
    assert compare_runs(first, second)["identical"]
    _, other = run("starter", seed=CFG.seed + 1, out_root=tmp_path / "b")
    result = compare_runs(first, other)
    assert not result["identical"] and "csv/employee.csv" in result["differing_files"]


# ------------------------------------------------------------------ persistence
def test_sqlite_load_is_repeatable_and_typed(starter, migrated_template, tmp_path):
    ds, manifest, _ = starter
    db = tmp_path / "load.sqlite3"
    shutil.copyfile(migrated_template, db)
    url = sqlite_url(db)
    assert load_dataset(ds.tables, url) == {t: manifest["tables"][t] for t in sorted(ds.tables)}
    assert load_dataset(ds.tables, url) == {t: manifest["tables"][t] for t in sorted(ds.tables)}
    engine = create_db_engine(url)
    assert not any("ground" in t for t in inspect(engine).get_table_names())
    with Session(engine) as s:
        line = s.scalar(
            select(DemandPlan).where(DemandPlan.demand_id == "DEM-PRJ-2026-000001-2026W01-01")
        )
        assert line is not None and isinstance(line.required_hours, Decimal)
        assert line.created_at.tzinfo is not None
    engine.dispose()


def test_sql_seed_loads_into_fresh_database(starter, migrated_template, tmp_path):
    _, manifest, folder = starter
    db = tmp_path / "seed.sqlite3"
    shutil.copyfile(migrated_template, db)
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript((folder / "sql" / "seed.sql").read_text(encoding="utf-8"))
    for table, n in manifest["tables"].items():
        assert con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == n, table
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    con.close()

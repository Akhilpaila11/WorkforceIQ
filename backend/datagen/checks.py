"""Validation of generated tables (BR-VAL-001..009) and the generator's reference anomaly finder.

The reference finder applies the documented rules (BR-UTL-004, BR-SKL-004, BR-DEM-004,
BR-ALC-003) to the generated records. It proves that the clean baseline contains no anomalies
and that, after injection, the anomalies present are exactly the labelled ground truth.
It is independent of the backend detection engine (Phase 5).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from itertools import pairwise
from typing import Any

from sqlalchemy import Enum

from app.db.registry import metadata
from app.domain.ids import EntityKind, is_valid_id, parse_demand_id
from datagen.anomalies import (
    ANOMALY_TYPES,
    CONFIG_KEY,
    CONFLICT,
    DUPLICATE,
    EXPIRED,
    OVERALLOCATION,
)
from datagen.capacity import WeekCapacity, group_by
from datagen.config import GeneratorConfig

Row = dict[str, Any]
ID_KIND = {
    "employee": EntityKind.EMPLOYEE,
    "role": EntityKind.ROLE,
    "skill": EntityKind.SKILL,
    "employee_skill": EntityKind.EMPLOYEE_SKILL,
    "project": EntityKind.PROJECT,
    "allocation": EntityKind.ALLOCATION,
    "availability": EntityKind.AVAILABILITY,
    "training": EntityKind.TRAINING,
}
DATE_RANGES = (
    ("employee", "hire_date", "termination_date"),
    ("employee_skill", "effective_from", "effective_to"),
    ("availability", "start_date", "end_date"),
    ("training", "start_date", "end_date"),
    ("project", "start_date", "end_date"),
    ("allocation", "start_date", "end_date"),
)


@dataclass(frozen=True)
class Check:
    name: str
    rule_id: str
    passed: bool
    detail: str


# ------------------------------------------------------------------ reference anomaly finder
def counted_demand(cfg: GeneratorConfig, tables: dict[str, list[Row]]) -> list[Row]:
    """BR-DEM-003: counted statuses, counted project statuses, week within project dates."""
    statuses = set(cfg.rule("BR-DEM-003", "counted_demand_statuses"))
    project_statuses = set(cfg.rule("BR-DEM-003", "counted_project_statuses"))
    projects = {p["project_id"]: p for p in tables["project"]}
    return [
        line
        for line in tables["demand_plan"]
        if line["status"] in statuses
        and projects[line["project_id"]]["status"] in project_statuses
        and line["week_start_date"] <= projects[line["project_id"]]["end_date"]
        and line["week_start_date"] + timedelta(days=6)
        >= projects[line["project_id"]]["start_date"]
    ]


def duplicate_lines(cfg: GeneratorConfig, tables: dict[str, list[Row]]) -> tuple[set[str], int]:
    """BR-DEM-004: all but the lowest line number per duplicate key -> (ids, population)."""
    primary = {
        r["demand_id"]: r
        for r in tables["demand_skill_requirement"]
        if r["requirement_type"] == "PRIMARY"
    }
    groups: dict[tuple[Any, ...], list[Row]] = defaultdict(list)
    counted = counted_demand(cfg, tables)
    for line in counted:
        p = primary[line["demand_id"]]
        groups[
            (
                line["project_id"],
                line["week_start_date"],
                line["role_id"],
                p["skill_id"],
                p["min_proficiency"],
            )
        ].append(line)
    dups = {
        line["demand_id"]
        for g in groups.values()
        if len(g) > 1
        for line in sorted(g, key=lambda x: x["line_no"])[1:]
    }
    return dups, len(counted)


def find_anomalies(
    cfg: GeneratorConfig, tables: dict[str, list[Row]], capacity: dict[str, WeekCapacity]
) -> tuple[dict[str, set[str]], dict[str, int]]:
    tol = float(cfg.rule("BR-UTL-004", "tolerance_hours"))
    found: dict[str, set[str]] = {t: set() for t in ANOMALY_TYPES}
    population: dict[str, int] = {}
    pop = 0
    for eid, cap in capacity.items():
        for w in range(cfg.horizon_weeks):
            if cap.gross[w] > 0 or cap.allocated[w] > 0:
                pop += 1
            if cap.allocated[w] > cap.net[w] + tol:
                found[OVERALLOCATION].add(f"{eid}|{cfg.weeks[w].isoformat()}")
    population[OVERALLOCATION] = pop
    current = [v for v in tables["employee_skill"] if v["effective_to"] is None]
    population[EXPIRED] = len(current)
    found[EXPIRED] = {
        v["employee_skill_id"]
        for v in current
        if v["recorded_status"] == "CURRENT"
        and v["expiry_date"] is not None
        and v["expiry_date"] < cfg.as_of
    }
    found[DUPLICATE], population[DUPLICATE] = duplicate_lines(cfg, tables)
    exclusive = set(cfg.rule("BR-ALC-003", "exclusive_allocation_types"))
    counted = set(cfg.rule("BR-CAP-008", "counted_allocation_statuses"))
    pairs = 0
    for rows in group_by(
        [a for a in tables["allocation"] if a["status"] in counted], "employee_id"
    ).values():
        ordered = sorted(rows, key=lambda a: a["start_date"])
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                if b["start_date"] > a["end_date"]:
                    break
                pairs += 1
                if a["allocation_type"] in exclusive or b["allocation_type"] in exclusive:
                    found[CONFLICT].add("|".join(sorted([a["allocation_id"], b["allocation_id"]])))
    population[CONFLICT] = pairs
    return found, population


# ------------------------------------------------------------------ structural validation
Tables = dict[str, list[Row]]


def _check(name: str, rule: str, problems: list[str]) -> Check:
    detail = "ok" if not problems else f"{len(problems)} problem(s): " + "; ".join(problems[:5])
    return Check(name, rule, not problems, detail)


def _primary_keys(tables: Tables) -> Check:
    problems: list[str] = []
    for name, rows in tables.items():
        pk = [c.name for c in metadata.tables[name].primary_key.columns]
        keys = Counter(tuple(r[c] for c in pk) for r in rows)
        problems += [f"{name} duplicate {k}" for k, n in keys.items() if n > 1]
        if name in ID_KIND:
            kind = ID_KIND[name]
            problems += [
                f"{name} bad id {r[pk[0]]}" for r in rows if not is_valid_id(kind, r[pk[0]])
            ]
    for line in tables["demand_plan"]:
        parts = parse_demand_id(line["demand_id"])
        fields = (line["project_id"], line["iso_year"], line["iso_week"], line["line_no"])
        if (parts.project_id, parts.iso_year, parts.iso_week, parts.line_no) != fields:
            problems.append(f"demand id/fields mismatch {line['demand_id']}")
    return _check("primary keys unique and well-formed", "BR-VAL-001", problems)


def _foreign_keys(tables: Tables) -> Check:
    problems: list[str] = []
    for name, rows in tables.items():
        for fk in metadata.tables[name].foreign_keys:
            parent, column = fk.column.table.name, fk.parent.name
            values = {r[column] for r in rows if r.get(column) is not None}
            parent_keys = {r[fk.column.name] for r in tables.get(parent, [])}
            problems += [f"{name}.{column}={v}" for v in sorted(values - parent_keys)[:3]]
    return _check("foreign keys resolve", "BR-VAL-002", problems)


def _enums_and_required(tables: Tables) -> Check:
    problems: list[str] = []
    for name, rows in tables.items():
        for col in metadata.tables[name].columns:
            key = col.name
            if isinstance(col.type, Enum):
                allowed = set(col.type.enums)
                problems += [
                    f"{name}.{key}={r[key]}"
                    for r in rows
                    if r.get(key) is not None and r[key] not in allowed
                ]
            if not col.nullable and col.identity is None and col.server_default is None:
                problems += [f"{name}.{key} is null" for r in rows if r.get(key) is None][:3]
    return _check("enum values valid and required fields present", "BR-VAL-003", problems)


def _dates(cfg: GeneratorConfig, tables: Tables) -> Check:
    problems: list[str] = []
    for table, start, end in DATE_RANGES:
        pk = next(iter(metadata.tables[table].primary_key.columns)).name
        problems += [
            f"{table} {x[pk]}" for x in tables[table] if x[end] is not None and x[end] < x[start]
        ]
    problems += [
        v["employee_skill_id"]
        for v in tables["employee_skill"]
        if v["expiry_date"] is not None and v["expiry_date"] <= v["last_verified_date"]
    ]
    for name in ("demand_plan", "demand_actual"):
        for r in tables[name]:
            week: date = r["week_start_date"]
            if (
                week.isoweekday() != 1
                or week.isocalendar()[:2] != (r["iso_year"], r["iso_week"])
                or not cfg.horizon_start <= week <= cfg.horizon_end
            ):
                problems.append(f"{name} week {week}")
    employees = {e["employee_id"]: e for e in tables["employee"]}
    for a in tables["allocation"]:
        emp = employees[a["employee_id"]]
        ends_late = emp["termination_date"] and a["end_date"] > emp["termination_date"]
        if a["start_date"] < emp["hire_date"] or ends_late:
            problems.append(f"allocation outside employment {a['allocation_id']}")
    return _check("date ranges ordered and within parents", "BR-VAL-004", problems)


def _capacity_identity(capacity: dict[str, WeekCapacity]) -> Check:
    problems: list[str] = []
    for eid, cap in capacity.items():
        if (cap.net < -1e-9).any() or (cap.leave + cap.training > cap.gross + 1e-9).any():
            problems.append(eid)
        if (abs(cap.gross - cap.leave - cap.training - cap.allocated - cap.free) > 0.01).any():
            problems.append(f"{eid} identity")
    return _check("capacity reconciliation identity", "BR-VAL-005", problems)


def _lifecycles(cfg: GeneratorConfig, tables: Tables) -> Check:
    problems: list[str] = []
    for emp in tables["employee"]:
        if emp["hire_date"] > cfg.as_of:
            expected = "PENDING_START"
        elif emp["termination_date"] and emp["termination_date"] <= cfg.as_of:
            expected = "TERMINATED"
        else:
            expected = "ACTIVE"
        if emp["status"] != expected:
            problems.append(emp["employee_id"])
    problems += [
        p["project_id"]
        for p in tables["project"]
        if (p["status"] in ("COMPLETED", "CANCELLED")) != (p["closed_date"] is not None)
    ]
    problems += [
        t["training_id"]
        for t in tables["training"]
        if (t["status"] == "COMPLETED") != (t["completion_date"] is not None)
    ]
    return _check("lifecycle states agree with dates", "BR-VAL-006", problems)


def _schedules(tables: Tables) -> Check:
    problems: list[str] = []
    hire = {e["employee_id"]: e["hire_date"] for e in tables["employee"]}
    schedules = [a for a in tables["availability"] if a["availability_type"] == "WORK_SCHEDULE"]
    for eid, rows in group_by(schedules, "employee_id").items():
        ordered = sorted(rows, key=lambda r: r["start_date"])
        if ordered[0]["start_date"] != hire[eid]:
            problems.append(f"{eid} schedule does not start at hire")
        for a, b in pairwise(ordered):
            if a["end_date"] is None or a["end_date"] + timedelta(days=1) != b["start_date"]:
                problems.append(f"{eid} schedule gap/overlap")
    scheduled = {a["employee_id"] for a in schedules}
    problems += [eid for eid in hire if eid not in scheduled]
    return _check("work schedules contiguous, non-overlapping", "BR-VAL-009", problems)


def _structure(tables: Tables) -> Check:
    kinds = Counter(
        (r["demand_id"], r["requirement_type"]) for r in tables["demand_skill_requirement"]
    )
    problems = [
        d["demand_id"]
        for d in tables["demand_plan"]
        if kinds[(d["demand_id"], "PRIMARY")] != 1
        or kinds[(d["demand_id"], "SECONDARY")] > 2
        or d["required_hours"] > d["headcount"] * 40
    ]
    current = Counter(
        (v["employee_id"], v["skill_id"])
        for v in tables["employee_skill"]
        if v["effective_to"] is None
    )
    problems += [f"{k} has {n} current versions" for k, n in current.items() if n != 1]
    cert = {s["skill_id"] for s in tables["skill"] if s["requires_certification"]}
    problems += [
        v["employee_skill_id"]
        for v in tables["employee_skill"]
        if v["skill_id"] in cert and v["expiry_date"] is None
    ]
    return _check("demand lines, skill versions, certifications", "BR-DEM-001", problems)


def _volumes(cfg: GeneratorConfig, tables: Tables) -> Check:
    expected = {
        "employee": cfg.volumes["employees"],
        "skill": cfg.volumes["skills"],
        "project": cfg.volumes["projects"],
        "role": cfg.volumes["roles"],
    }
    problems = [f"{t}: {len(tables[t])} != {n}" for t, n in expected.items() if len(tables[t]) != n]
    return _check("configured volumes", "BR-VAL-001", problems)


def _anomalies(
    cfg: GeneratorConfig,
    tables: Tables,
    capacity: dict[str, WeekCapacity],
    ground_truth: list[Row] | None,
) -> Check:
    """Baseline: no anomalies at all. After injection: exactly the labelled ground truth."""
    found, _ = find_anomalies(cfg, tables, capacity)
    if ground_truth is None:
        problems = [f"{t}: {len(keys)}" for t, keys in found.items() if keys]
        return _check("baseline contains no anomalies", "BR-VAL-008", problems)
    problems = []
    for kind in ANOMALY_TYPES:
        labelled = {g["evaluation_key"] for g in ground_truth if g["anomaly_type"] == kind}
        if labelled != found[kind]:
            problems.append(f"{kind}: found {len(found[kind])}, labelled {len(labelled)}")
        events = len({g["injection_event"] for g in ground_truth if g["anomaly_type"] == kind})
        if events != cfg.anomalies[CONFIG_KEY[kind]]:
            problems.append(f"{kind}: {events} events != {cfg.anomalies[CONFIG_KEY[kind]]}")
    return _check("anomalies present == ground truth", "BR-VAL-008", problems)


def validate(
    cfg: GeneratorConfig,
    tables: Tables,
    capacity: dict[str, WeekCapacity],
    ground_truth: list[Row] | None,
) -> list[Check]:
    present = {name: rows for name, rows in tables.items() if name in metadata.tables}
    return [
        _primary_keys(present),
        _foreign_keys(present),
        _enums_and_required(present),
        _dates(cfg, tables),
        _capacity_identity(capacity),
        _lifecycles(cfg, tables),
        _schedules(tables),
        _structure(tables),
        _volumes(cfg, tables),
        _anomalies(cfg, tables, capacity, ground_truth),
    ]


def summarize(checks: list[Check]) -> list[dict[str, Any]]:
    return [asdict(c) for c in checks]

"""Master and people data: roles, skills, role_skill, employees, work schedules, skill
profiles (versioned), leave and training. IDs are assigned in a deterministic sort order."""

from __future__ import annotations

import calendar as _calendar
import re
from datetime import date, timedelta
from typing import Any

from app.domain.ids import EntityKind, format_id
from datagen.config import GeneratorConfig
from datagen.rng import pick, sample, stage_faker, stage_rng
from datagen.vocabulary import ROLE_BY_CODE, ROLES, skill_catalogue, skill_code

Row = dict[str, Any]
SENIORITY = ("JUNIOR", "MID", "SENIOR", "LEAD", "PRINCIPAL")
SENIORITY_P = (0.20, 0.35, 0.28, 0.12, 0.05)
SENIORITY_SHIFT = {"JUNIOR": -1, "MID": 0, "SENIOR": 0, "LEAD": 1, "PRINCIPAL": 1}
CERT_WEIGHT = {"CLOUD": 3.0, "SECURITY": 3.0, "DEVOPS": 1.5, "MANAGEMENT": 1.0}
EARLIEST_HIRE = date(2012, 1, 2)


# ------------------------------------------------------------------ date helpers
def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, _calendar.monthrange(year, month)[1]))


def add_working_days(first: date, n: int) -> date:
    """Date of the n-th working day counting ``first`` (a working day) as day 1."""
    d, counted = first, 1
    while counted < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            counted += 1
    return d


def effective_status(row: Row, on: date, freshness_days: int) -> str:
    """BR-SKL-002 (first match wins)."""
    if row["expiry_date"] is not None and row["expiry_date"] < on:
        return "EXPIRED"
    if row["recorded_status"] == "PENDING_VERIFICATION":
        return "PENDING"
    if (on - row["last_verified_date"]).days > freshness_days:
        return "STALE"
    return "VALID"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


# ------------------------------------------------------------------ roles & skills
def build_roles(cfg: GeneratorConfig) -> list[Row]:
    return [
        {
            "role_id": format_id(EntityKind.ROLE, i),
            "code": r.code,
            "name": r.name,
            "role_family": r.family.value,
            "description": f"{r.name} ({r.family.value.replace('_', ' ').title()} family)",
            "is_active": True,
        }
        for i, r in enumerate(ROLES[: cfg.volumes["roles"]], 1)
    ]


def build_skills(cfg: GeneratorConfig) -> list[Row]:
    rng = stage_rng(cfg.seed, "skills")
    catalogue = skill_catalogue()[: cfg.volumes["skills"]]
    if len(catalogue) < cfg.volumes["skills"]:
        raise ValueError(f"vocabulary has only {len(catalogue)} skills")
    weights = [CERT_WEIGHT.get(cat.value, 0.4) for _, cat in catalogue]
    n_cert = round(cfg.supply["certification_skill_share"] * len(catalogue))
    p = [w / sum(weights) for w in weights]
    cert_idx = set(rng.choice(len(catalogue), size=n_cert, replace=False, p=p).tolist())
    validity = cfg.supply["certification_validity_months"]
    rows = []
    for i, (name, cat) in enumerate(catalogue):
        cert = i in cert_idx
        rows.append(
            {
                "skill_id": format_id(EntityKind.SKILL, i + 1),
                "code": skill_code(name),
                "name": name,
                "category": cat.value,
                "requires_certification": cert,
                "validity_months": int(pick(rng, validity)) if cert else None,
                "description": None,
                "is_active": True,
            }
        )
    return rows


def build_role_skills(cfg: GeneratorConfig, roles: list[Row], skills: list[Row]) -> list[Row]:
    rng = stage_rng(cfg.seed, "role_skill")
    by_cat: dict[str, list[str]] = {}
    for s in skills:
        by_cat.setdefault(s["category"], []).append(s["skill_id"])
    rows: list[Row] = []
    for role in roles:
        cats = [c.value for c in ROLE_BY_CODE[role["code"]].categories]
        core = sample(rng, by_cat.get(cats[0], []), 3)
        others = [s for c in cats[1:] for s in by_cat.get(c, []) if s not in core]
        if len(core) < 2:  # tiny vocabularies: borrow from the secondary categories
            core += sample(rng, others, 2 - len(core))
        supporting = sample(rng, [s for s in others if s not in core], int(rng.integers(2, 5)))
        rows += [
            {
                "role_id": role["role_id"],
                "skill_id": s,
                "importance": "CORE",
                "typical_min_proficiency": 3,
            }
            for s in core
        ]
        rows += [
            {
                "role_id": role["role_id"],
                "skill_id": s,
                "importance": "SUPPORTING",
                "typical_min_proficiency": 2,
            }
            for s in supporting
        ]
    return sorted(rows, key=lambda r: (r["role_id"], r["skill_id"]))


# ------------------------------------------------------------------ employees & schedules
def build_employees(cfg: GeneratorConfig, roles: list[Row]) -> list[Row]:
    rng = stage_rng(cfg.seed, "employees")
    fake = stage_faker(cfg.seed, "employees")
    offices = sorted({fake.city() for _ in range(40)})[:8]
    weights = [ROLE_BY_CODE[r["code"]].weight for r in roles]
    n = cfg.volumes["employees"]
    span_before = (cfg.horizon_start - EARLIEST_HIRE).days
    rows = []
    for i in range(1, n + 1):
        role = roles[i - 1] if i <= len(roles) else pick(rng, roles, weights)  # every role staffed
        if rng.random() < 0.05:  # joins during the horizon
            hire = cfg.horizon_start + timedelta(
                days=int(rng.integers(0, cfg.horizon_weeks * 7 - 14))
            )
        else:
            hire = EARLIEST_HIRE + timedelta(days=int(rng.integers(0, span_before)))
        termination = None
        if hire < cfg.horizon_start and rng.random() < 0.03:  # leaves during the horizon
            termination = cfg.horizon_start + timedelta(
                days=int(rng.integers(7, cfg.horizon_weeks * 7))
            )
        if hire > cfg.as_of:
            status = "PENDING_START"
        elif termination is not None and termination <= cfg.as_of:
            status = "TERMINATED"
        else:
            status = "ACTIVE"
        first, last = fake.first_name(), fake.last_name()
        rows.append(
            {
                "employee_id": format_id(EntityKind.EMPLOYEE, i),
                "first_name": first,
                "last_name": last,
                "email": f"{_slug(first)}.{_slug(last)}.{i:06d}@example.com",
                "role_id": role["role_id"],
                "seniority": pick(rng, SENIORITY, SENIORITY_P),
                "location": pick(rng, offices),
                "hire_date": hire,
                "termination_date": termination,
                "status": status,
            }
        )
    return rows


def build_schedules(cfg: GeneratorConfig, employees: list[Row]) -> list[Row]:
    rng = stage_rng(cfg.seed, "schedules")
    pt_hours = [float(h) for h in cfg.supply["part_time_weekly_hours"]]
    full = float(cfg.rule("BR-CAP-001", "standard_weekly_hours"))
    rows = []
    for e in employees:
        hours = pick(rng, pt_hours) if rng.random() < cfg.supply["part_time_share"] else full
        change = None
        if rng.random() < 0.03:  # contract change mid-horizon (effective-dated, A-06)
            change = cfg.horizon_start + timedelta(weeks=int(rng.integers(2, cfg.horizon_weeks)))
            if change <= e["hire_date"]:
                change = None
        base = {
            "employee_id": e["employee_id"],
            "availability_type": "WORK_SCHEDULE",
            "hours_per_day": None,
            "status": "APPROVED",
            "reason": None,
        }
        if change is None:
            rows.append(
                base | {"start_date": e["hire_date"], "end_date": None, "weekly_hours": hours}
            )
        else:
            new_hours = full if hours < full else pick(rng, pt_hours)
            rows.append(
                base
                | {
                    "start_date": e["hire_date"],
                    "end_date": change - timedelta(1),
                    "weekly_hours": hours,
                }
            )
            rows.append(
                base
                | {
                    "start_date": change,
                    "end_date": None,
                    "weekly_hours": new_hours,
                    "reason": "Contract hours changed",
                }
            )
    return rows


# ------------------------------------------------------------------ skill profiles
def build_employee_skills(
    cfg: GeneratorConfig,
    roles: list[Row],
    employees: list[Row],
    role_skills: list[Row],
    skills: list[Row],
) -> tuple[list[Row], list[Row]]:
    """Current + historical skill versions, and the completed trainings behind some of them."""
    rng = stage_rng(cfg.seed, "employee_skills")
    skill_by_id = {s["skill_id"]: s for s in skills}
    by_role: dict[str, list[Row]] = {}
    for rs in role_skills:
        by_role.setdefault(rs["role_id"], []).append(rs)
    by_cat: dict[str, list[str]] = {}
    for s in skills:
        by_cat.setdefault(s["category"], []).append(s["skill_id"])
    weights = cfg.supply["proficiency_weights"]
    lo, hi = cfg.supply["skills_per_employee"]
    max_age = cfg.supply["verification_max_age_days"]
    versions: list[Row] = []
    trainings: list[Row] = []
    role_code = {r["role_id"]: r["code"] for r in roles}
    for e in employees:
        k = int(rng.integers(lo, hi + 1))
        chosen: list[str] = []
        for rs in by_role.get(e["role_id"], []):
            if rng.random() < (0.9 if rs["importance"] == "CORE" else 0.6):
                chosen.append(rs["skill_id"])
        family_pool = [
            s
            for cat in ROLE_BY_CODE[role_code[e["role_id"]]].categories
            for s in by_cat.get(cat.value, [])
            if s not in chosen
        ]
        chosen += sample(rng, family_pool, max(0, k - len(chosen)))
        rest = [s["skill_id"] for s in skills if s["skill_id"] not in chosen]
        chosen += sample(rng, rest, max(0, k - len(chosen)))
        for skill_id in sorted(chosen):
            skill = skill_by_id[skill_id]
            level = int(rng.choice(5, p=weights)) + 1 + SENIORITY_SHIFT[e["seniority"]]
            level = min(5, max(1, level))
            verified = cfg.as_of - timedelta(days=int(rng.integers(0, max_age + 1)))
            pending = rng.random() < cfg.supply["pending_verification_share"]
            cert = skill["requires_certification"]
            expiry = add_months(verified, skill["validity_months"]) if cert else None
            if expiry is not None and expiry < cfg.as_of:
                recorded = "EXPIRED"
            elif pending:
                recorded = "PENDING_VERIFICATION"
            else:
                recorded = "CURRENT"
            if pending:
                source = "SELF"
            elif cert:
                source = "CERTIFICATION"
            else:
                source = pick(rng, ("SELF", "MANAGER", "ASSESSMENT"), (0.25, 0.45, 0.30))
            current = {
                "employee_id": e["employee_id"],
                "skill_id": skill_id,
                "proficiency_level": level,
                "assessment_source": source,
                "last_verified_date": verified,
                "expiry_date": expiry,
                "recorded_status": recorded,
                "effective_from": verified,
                "effective_to": None,
            }
            versions.append(current)
            if level >= 2 and rng.random() < 0.25:  # an earlier, lower assessment (SCD2)
                prev_from = verified - timedelta(days=int(rng.integers(180, 721)))
                versions.append(
                    current
                    | {
                        "proficiency_level": level - 1,
                        "assessment_source": "SELF" if pending else pick(rng, ("SELF", "MANAGER")),
                        "last_verified_date": prev_from,
                        "expiry_date": add_months(prev_from, skill["validity_months"])
                        if cert
                        else None,
                        "recorded_status": "CURRENT",
                        "effective_from": prev_from,
                        "effective_to": verified - timedelta(days=1),
                    }
                )
                weeks = int(rng.integers(4, 9))
                t_start = verified - timedelta(weeks=weeks)
                if (
                    not pending
                    and verified < cfg.horizon_start
                    and t_start >= e["hire_date"]
                    and rng.random() < 0.4
                ):
                    current["assessment_source"] = "CERTIFICATION" if cert else "TRAINING"
                    trainings.append(
                        {
                            "employee_id": e["employee_id"],
                            "skill_id": skill_id,
                            "recommendation_id": None,
                            "_outcome_key": (e["employee_id"], skill_id, verified),
                            "training_type": "CERTIFICATION" if cert else "COURSE",
                            "target_proficiency": level,
                            "start_date": t_start,
                            "end_date": verified,
                            "hours_per_week": float(pick(rng, (4.0, 6.0, 8.0))),
                            "status": "COMPLETED",
                            "completion_date": verified,
                        }
                    )
    versions.sort(key=lambda r: (r["employee_id"], r["skill_id"], r["effective_from"]))
    for i, v in enumerate(versions, 1):
        v["employee_skill_id"] = format_id(EntityKind.EMPLOYEE_SKILL, i)
    key_to_id = {
        (v["employee_id"], v["skill_id"], v["effective_from"]): v["employee_skill_id"]
        for v in versions
    }
    for t in trainings:
        t["outcome_employee_skill_id"] = key_to_id[t.pop("_outcome_key")]
    return versions, trainings


# ------------------------------------------------------------------ leave & training
def build_leave(cfg: GeneratorConfig, employees: list[Row]) -> list[Row]:
    rng = stage_rng(cfg.seed, "leave")
    frac = cfg.horizon_weeks / 52
    max_block = 5 if cfg.horizon_weeks < 20 else 10
    rows: list[Row] = []
    for e in employees:
        first = max(e["hire_date"], cfg.horizon_start)
        last = min(e["termination_date"] or cfg.horizon_end, cfg.horizon_end)
        workdays = [
            first + timedelta(days=i)
            for i in range((last - first).days + 1)
            if (first + timedelta(days=i)).weekday() < 5
        ]
        if len(workdays) < 15:
            continue
        budget = round(cfg.supply["annual_leave_days_per_year"] * frac * rng.uniform(0.5, 1.5))
        while budget > 0:
            length = min(budget, int(rng.integers(1, max_block + 1)))
            start = workdays[int(rng.integers(0, len(workdays) - length))]
            end = min(add_working_days(start, length), last)
            status = pick(rng, ("APPROVED", "REQUESTED", "REJECTED"), (0.94, 0.04, 0.02))
            rows.append(
                {
                    "employee_id": e["employee_id"],
                    "availability_type": "ANNUAL_LEAVE",
                    "start_date": start,
                    "end_date": end,
                    "weekly_hours": None,
                    "hours_per_day": None,
                    "status": status,
                    "reason": None,
                }
            )
            budget -= length
        for _ in range(int(rng.poisson(cfg.supply["sick_leave_episodes_per_year"] * frac))):
            start = workdays[int(rng.integers(0, len(workdays)))]
            partial = rng.random() < 0.25
            end = start if partial else min(add_working_days(start, int(rng.integers(1, 4))), last)
            rows.append(
                {
                    "employee_id": e["employee_id"],
                    "availability_type": "SICK_LEAVE",
                    "start_date": start,
                    "end_date": end,
                    "weekly_hours": None,
                    "hours_per_day": 4.0 if partial else None,
                    "status": "APPROVED",
                    "reason": None,
                }
            )
    return rows


def build_horizon_trainings(
    cfg: GeneratorConfig,
    employees: list[Row],
    role_skills: list[Row],
    versions: list[Row],
    skills: list[Row],
) -> list[Row]:
    """In-progress / planned trainings around ``as_of`` (they consume capacity, BR-CAP-006)."""
    rng = stage_rng(cfg.seed, "trainings")
    cert = {s["skill_id"]: s["requires_certification"] for s in skills}
    current = {(v["employee_id"], v["skill_id"]): v for v in versions if v["effective_to"] is None}
    supporting: dict[str, list[str]] = {}
    for rs in role_skills:
        supporting.setdefault(rs["role_id"], []).append(rs["skill_id"])
    eligible = [
        e
        for e in employees
        if e["termination_date"] is None and e["hire_date"] <= cfg.as_of - timedelta(weeks=2)
    ]
    remaining_weeks = cfg.holdout_weeks  # weeks from as_of to the horizon end
    rows = []
    for e in sample(rng, eligible, round(0.04 * len(employees))):
        options = supporting.get(e["role_id"], [])
        if not options:
            continue
        skill_id = pick(rng, options)
        held = current.get((e["employee_id"], skill_id))
        if held is not None and held["proficiency_level"] >= 5:
            continue
        target = held["proficiency_level"] + 1 if held else 2
        k = int(rng.integers(-1, max(0, remaining_weeks - 2)))
        start = cfg.as_of + timedelta(weeks=k)
        weeks = int(rng.integers(2, 7))
        end = min(start + timedelta(weeks=weeks, days=-3), cfg.horizon_end)
        rows.append(
            {
                "employee_id": e["employee_id"],
                "skill_id": skill_id,
                "recommendation_id": None,
                "outcome_employee_skill_id": None,
                "training_type": "CERTIFICATION"
                if cert[skill_id]
                else pick(rng, ("COURSE", "MENTORING")),
                "target_proficiency": target,
                "start_date": start,
                "end_date": end,
                "hours_per_week": float(pick(rng, (4.0, 6.0, 8.0))),
                "status": "IN_PROGRESS" if start <= cfg.as_of else "PLANNED",
                "completion_date": None,
            }
        )
    return rows


def assign_year_ids(
    rows: list[Row], kind: EntityKind, id_col: str, sort_cols: tuple[str, ...], start_seq: int = 1
) -> int:
    """Sort rows deterministically and assign ``PREFIX-<start year>-<seq>`` IDs."""
    rows.sort(key=lambda r: tuple(r[c] for c in sort_cols))
    seq = start_seq - 1
    for seq, r in enumerate(rows, start_seq):
        r[id_col] = format_id(kind, seq, year=r["start_date"].year)
    return seq

"""Projects, weekly demand lines, allocations and synthetic actuals.

Demand is scaled so that total planned hours = ``demand_to_capacity_ratio`` x total net
capacity (computed from schedules, leave and training). Allocations are placed against the
computed weekly capacity, so the clean baseline never over-allocates and never overlaps a
DEDICATED assignment (docs/06 section 4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np

from app.domain.calendar import iso_week_of
from app.domain.ids import EntityKind, demand_id, format_id
from datagen.capacity import CapacityModel, WeekCapacity
from datagen.config import GeneratorConfig
from datagen.master import effective_status
from datagen.rng import pick, round_half, sample, stage_faker, stage_rng
from datagen.vocabulary import BUSINESS_UNITS, PROJECT_THEMES, ROLE_BY_CODE

Row = dict[str, Any]
PRIORITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
PRIORITY_P = (0.10, 0.30, 0.40, 0.20)
STAFFED_PROJECT_STATUSES = {"APPROVED", "ACTIVE", "COMPLETED"}


@dataclass
class LineGroup:
    """All weekly lines of one (project, role, primary skill)."""

    project: Row
    role: Row
    skill_id: str
    min_proficiency: int
    secondary: list[str]
    weekly: np.ndarray = field(default_factory=lambda: np.zeros(0))


# ------------------------------------------------------------------ projects
def build_projects(cfg: GeneratorConfig) -> list[Row]:
    """30 % of projects kick off on 1 January of the planning year; the rest start later."""
    rng = stage_rng(cfg.seed, "projects")
    fake = stage_faker(cfg.seed, "projects")
    kickoff = date(cfg.planning_year, 1, 1)
    latest_start = cfg.horizon_end - timedelta(weeks=4)
    max_weeks = max(26, int(cfg.horizon_weeks * 0.8))
    drafts: list[tuple[date, int, Row]] = []
    for i in range(cfg.volumes["projects"]):
        start = (
            kickoff
            if rng.random() < 0.3
            else kickoff + timedelta(days=int(rng.integers(0, (latest_start - kickoff).days + 1)))
        )
        end = start + timedelta(weeks=int(rng.integers(6, max_weeks + 1)), days=-1)
        if end < cfg.as_of:
            status, closed = "COMPLETED", end
        elif start > cfg.as_of:
            status, closed = ("PROPOSED" if rng.random() < 0.1 else "APPROVED"), None
        else:
            status, closed = "ACTIVE", None
        drafts.append(
            (
                start,
                i,
                {
                    "name": f"{fake.last_name()} {pick(rng, PROJECT_THEMES)}",
                    "client_name": fake.company() if rng.random() < 0.85 else None,
                    "business_unit": pick(rng, BUSINESS_UNITS),
                    "priority": pick(rng, PRIORITIES, PRIORITY_P),
                    "status": status,
                    "start_date": start,
                    "end_date": end,
                    "closed_date": closed,
                },
            )
        )
    drafts.sort(key=lambda d: (d[0], d[1]))
    return [
        {"project_id": format_id(EntityKind.PROJECT, n, year=d[2]["start_date"].year)} | d[2]
        for n, d in enumerate(drafts, 1)
    ]


# ------------------------------------------------------------------ demand
def _curve(week_idx: int, total: int) -> float:
    ramp_up, ramp_down = max(1, round(total * 0.2)), max(1, round(total * 0.15))
    if week_idx < ramp_up:
        return 0.5 + 0.5 * (week_idx + 1) / ramp_up
    if week_idx >= total - ramp_down:
        return 0.5 + 0.5 * (total - week_idx) / ramp_down
    return 1.0


def build_demand_groups(
    cfg: GeneratorConfig, projects: list[Row], roles: list[Row], role_skills: list[Row]
) -> list[LineGroup]:
    rng = stage_rng(cfg.seed, "demand")
    model = CapacityModel(cfg)
    core: dict[str, list[str]] = {}
    support: dict[str, list[str]] = {}
    for rs in role_skills:
        (core if rs["importance"] == "CORE" else support).setdefault(rs["role_id"], []).append(
            rs["skill_id"]
        )
    weights = np.asarray([ROLE_BY_CODE[r["code"]].weight for r in roles], dtype=float)
    lo, hi = cfg.demand["roles_per_project"]
    mix: list[set[int]] = []
    for _ in projects:
        n_roles = min(len(roles), int(rng.integers(lo, hi + 1)))
        mix.append(
            {
                int(i)
                for i in rng.choice(
                    len(roles), size=n_roles, replace=False, p=weights / weights.sum()
                )
            }
        )
    for i in range(len(roles)):  # every role is needed somewhere (rebalanced in scale_demand)
        if not any(i in m for m in mix):
            min(mix, key=len).add(i)
    groups: list[LineGroup] = []
    for p, chosen in zip(projects, mix, strict=True):
        total_weeks = math.ceil(((p["end_date"] - p["start_date"]).days + 1) / 7)
        for role in sorted((roles[i] for i in chosen), key=lambda r: r["code"]):
            options = core.get(role["role_id"], [])
            primaries = sample(rng, options, 2 if rng.random() < 0.2 else 1)
            for skill_id in sorted(primaries):
                base = int(rng.integers(1, 4)) * 40 * rng.uniform(0.5, 1.0)
                weekly = np.zeros(cfg.horizon_weeks)
                for w, monday in enumerate(cfg.weeks):
                    sunday = monday + timedelta(days=6)
                    if sunday < p["start_date"] or monday > p["end_date"]:
                        continue
                    k = (monday - p["start_date"]).days // 7 if monday >= p["start_date"] else 0
                    part = model.prorated_hours(1.0, p["start_date"], p["end_date"], monday)
                    weekly[w] = base * _curve(k, total_weeks) * part
                extra = [s for s in support.get(role["role_id"], []) if s != skill_id]
                groups.append(
                    LineGroup(
                        project=p,
                        role=role,
                        skill_id=skill_id,
                        min_proficiency=int(pick(rng, (2, 3, 4), (0.2, 0.55, 0.25))),
                        secondary=sorted(sample(rng, extra, int(rng.integers(0, 3)))),
                        weekly=weekly,
                    )
                )
    return groups


def scale_demand(cfg: GeneratorConfig, groups: list[LineGroup], role_net: dict[str, float]) -> None:
    """Role demand ~ role net supply x scarcity factor (lognormal), then normalised so that
    total planned hours = demand_to_capacity_ratio x total net capacity."""
    rng = stage_rng(cfg.seed, "demand_scale")
    counted = [g for g in groups if g.project["status"] != "PROPOSED"]
    raw: dict[str, float] = {}
    for g in counted:
        raw[g.role["role_id"]] = raw.get(g.role["role_id"], 0.0) + float(g.weekly.sum())
    factor = {
        rid: role_net.get(rid, 0.0) * float(rng.lognormal(0.0, 0.35)) / total
        for rid, total in sorted(raw.items())
        if total > 0
    }
    scaled = sum(float(g.weekly.sum()) * factor.get(g.role["role_id"], 0.0) for g in counted)
    norm = cfg.demand["demand_to_capacity_ratio"] * sum(role_net.values()) / scaled if scaled else 0
    for g in groups:
        f = factor.get(g.role["role_id"], 0.0) * norm
        g.weekly = np.array([round_half(h * f) if h * f >= 1 else 0.0 for h in g.weekly])


def build_demand_lines(
    cfg: GeneratorConfig, groups: list[LineGroup]
) -> tuple[list[Row], list[Row]]:
    rng = stage_rng(cfg.seed, "demand_status")
    lines: list[Row] = []
    reqs: list[Row] = []
    per_week: dict[tuple[str, int], list[LineGroup]] = {}
    for g in groups:
        for w in np.nonzero(g.weekly)[0]:
            per_week.setdefault((g.project["project_id"], int(w)), []).append(g)
    standard = float(cfg.rule("BR-CAP-001", "standard_weekly_hours"))
    for (project_id, w), gs in sorted(per_week.items()):
        monday = cfg.weeks[w]
        iso = iso_week_of(monday)
        for line_no, g in enumerate(sorted(gs, key=lambda x: (x.role["code"], x.skill_id)), 1):
            hours = float(g.weekly[w])
            status = g.project["status"]
            if status == "PROPOSED":
                line_status = "DRAFT"
            else:
                line_status = "APPROVED" if rng.random() < 0.92 else "SUBMITTED"
            did = demand_id(project_id, iso.year, iso.week, line_no)
            lines.append(
                {
                    "demand_id": did,
                    "project_id": project_id,
                    "role_id": g.role["role_id"],
                    "iso_year": iso.year,
                    "iso_week": iso.week,
                    "week_start_date": monday,
                    "line_no": line_no,
                    "required_hours": hours,
                    "headcount": max(1, math.ceil(hours / standard)),
                    "status": line_status,
                    "source": "PROJECT_PLAN",
                }
            )
            reqs.append(
                {
                    "demand_id": did,
                    "skill_id": g.skill_id,
                    "requirement_type": "PRIMARY",
                    "min_proficiency": g.min_proficiency,
                }
            )
            reqs += [
                {
                    "demand_id": did,
                    "skill_id": s,
                    "requirement_type": "SECONDARY",
                    "min_proficiency": 2,
                }
                for s in g.secondary
            ]
    return lines, reqs


# ------------------------------------------------------------------ allocations
def build_allocations(
    cfg: GeneratorConfig,
    groups: list[LineGroup],
    employees: list[Row],
    capacity: dict[str, WeekCapacity],
    current_skills: dict[tuple[str, str], Row],
    roles: list[Row],
) -> list[Row]:
    rng = stage_rng(cfg.seed, "allocations")
    model = CapacityModel(cfg)
    freshness = int(cfg.rule("BR-SKL-002", "freshness_days"))
    family = {r["role_id"]: r["role_family"] for r in roles}
    emp_ids = [e["employee_id"] for e in employees]
    emp_by_id = {e["employee_id"]: e for e in employees}
    n, weeks = len(emp_ids), cfg.horizon_weeks
    net = np.array([capacity[e].net for e in emp_ids])
    bench = set(sample(rng, emp_ids, round(cfg.demand["bench_share"] * n)))
    mean = float(cfg.demand["target_mean_utilization"])  # per-employee booking ceiling
    target = rng.uniform(max(0.3, mean - 0.2), min(1.0, mean + 0.2), size=n)
    cap_left = net * target[:, None]
    has_alloc = np.zeros((n, weeks), dtype=bool)
    exclusive = np.zeros((n, weeks), dtype=bool)
    pool_lists: dict[str, list[int]] = {}
    for i, e in enumerate(employees):
        if e["employee_id"] not in bench:
            pool_lists.setdefault(family[e["role_id"]], []).append(i)
    pools = {f: np.array(v) for f, v in pool_lists.items()}
    position = {f: {int(i): k for k, i in enumerate(v)} for f, v in pools.items()}
    role_of = np.array([e["role_id"] for e in employees])
    emp_index = {eid: i for i, eid in enumerate(emp_ids)}
    holders: dict[str, list[tuple[int, int, bool]]] = {}  # skill -> (employee, level, valid)
    for (eid, sid), v in sorted(current_skills.items()):
        valid = effective_status(v, cfg.as_of, freshness) == "VALID"
        holders.setdefault(sid, []).append((emp_index[eid], v["proficiency_level"], valid))
    rank = {p: i for i, p in enumerate(PRIORITIES)}
    ordered = sorted(
        (g for g in groups if g.project["status"] in STAFFED_PROJECT_STATUSES),
        key=lambda g: (
            rank[g.project["priority"]],
            g.project["project_id"],
            g.role["code"],
            g.skill_id,
        ),
    )
    rows: list[Row] = []
    for g in ordered:
        need = g.weekly * rng.uniform(0.7, 1.0)  # staffed share; the rest stays a real gap
        fam = g.role["role_family"]
        if fam not in pools:
            continue
        pool = pools[fam]
        # score: qualified skill holder (2) > other holder (0.5); exact role (+1); random tie-break
        score = (role_of[pool] == g.role["role_id"]).astype(float) + rng.random(len(pool)) * 0.5
        for i, level, valid in holders.get(g.skill_id, []):
            k = position[fam].get(i)
            if k is not None:
                score[k] += 2.0 if valid and level >= g.min_proficiency else 0.5
        for i in (int(pool[j]) for j in np.argsort(-score, kind="stable")[:40]):
            open_weeks = np.nonzero(need > 0.5)[0]
            if open_weeks.size == 0:
                break
            usable = (
                (cap_left[i, open_weeks] >= 4)
                & ~exclusive[i, open_weeks]
                & (net[i, open_weeks] > 0)
            )
            if not usable.any():
                continue
            # Book what this person can actually take (median free room), capped by the need.
            room = float(np.median(cap_left[i, open_weeks][usable]))
            h = math.floor(min(40.0, room, max(4.0, float(np.median(need[open_weeks])))) * 2) / 2
            if h < 4:
                continue
            ok = usable & (cap_left[i, open_weeks] >= h)
            runs = _runs(open_weeks[ok])
            dedicated = rng.random() < cfg.demand["dedicated_allocation_share"] and all(
                not has_alloc[i, r].any() for r in runs
            )
            emp = emp_by_id[emp_ids[i]]
            for run in runs:
                hours = h
                if dedicated:
                    # Exclusive assignment sized to ~80 % of the person's week: it blocks the
                    # whole week, and the remaining slack is needed by docs/06 section 6.
                    hours = round_half(
                        min(0.8 * float(net[i, run].min()), float(cap_left[i, run].min()))
                    )
                    if hours < max(4.0, 0.5 * float(net[i, run].min())):
                        hours, dedicated = h, False
                start = max(g.project["start_date"], cfg.weeks[run[0]])
                end = min(g.project["end_date"], cfg.weeks[run[-1]] + timedelta(days=6))
                if emp["termination_date"] is not None:
                    end = min(end, emp["termination_date"])
                start = max(start, emp["hire_date"])
                if start > end:
                    continue
                for w in run:
                    booked = model.prorated_hours(hours, start, end, cfg.weeks[w])
                    cap_left[i, w] -= booked
                    need[w] -= booked
                    has_alloc[i, w] = True
                    exclusive[i, w] |= dedicated
                if end < cfg.as_of:
                    status = "COMPLETED"
                elif start >= cfg.as_of and rng.random() < 0.1:
                    status = "PROPOSED"
                else:
                    status = "CONFIRMED"
                rows.append(
                    {
                        "employee_id": emp["employee_id"],
                        "project_id": g.project["project_id"],
                        "role_id": g.role["role_id"],
                        "start_date": start,
                        "end_date": end,
                        "hours_per_week": hours,
                        "allocation_type": "DEDICATED" if dedicated else "SHARED",
                        "status": status,
                        "notes": None,
                    }
                )
    return rows


def _runs(weeks: np.ndarray) -> list[np.ndarray]:
    if weeks.size == 0:
        return []
    breaks = np.nonzero(np.diff(weeks) > 1)[0] + 1
    return [r for r in np.split(weeks, breaks) if r.size > 0]


# ------------------------------------------------------------------ actuals
def build_actuals(
    cfg: GeneratorConfig, lines: list[Row], projects: list[Row], roles: list[Row]
) -> list[Row]:
    """Synthetic timesheets from the CLEAN plan (docs/06 section 5); never a copy of it."""
    rng = stage_rng(cfg.seed, "actuals")
    a = cfg.actuals
    status = {p["project_id"]: p["status"] for p in projects}
    planned: dict[tuple[str, str, date], float] = {}
    for line in lines:
        if status[line["project_id"]] in STAFFED_PROJECT_STATUSES:
            key = (line["project_id"], line["role_id"], line["week_start_date"])
            planned[key] = planned.get(key, 0.0) + line["required_hours"]
    rows: list[Row] = []
    by_project: dict[str, list[tuple[str, date]]] = {}
    for pid, rid, wk in sorted(planned):
        by_project.setdefault(pid, []).append((rid, wk))
    for pid in sorted(by_project):
        realization = rng.normal(a["project_realization_mean"], a["project_realization_sd"])
        scope_from = cancel_from = None
        if rng.random() < a["scope_change_probability"]:
            scope_from = pick(rng, cfg.weeks)
        scope = rng.uniform(*a["scope_change_factor_range"])
        if rng.random() < a["cancellation_probability"]:
            cancel_from = pick(rng, cfg.weeks)
        project_roles = {rid for rid, _ in by_project[pid]}
        for rid, wk in by_project[pid]:
            value = planned[(pid, rid, wk)] * realization * rng.normal(1.0, a["weekly_noise_sd"])
            if scope_from is not None and wk >= scope_from:
                value *= scope
            if cancel_from is not None and wk >= cancel_from:
                value = 0.0
            rows.append(_actual(pid, rid, wk, value))
        weeks = sorted({wk for _, wk in by_project[pid]})
        others = [r["role_id"] for r in roles if r["role_id"] not in project_roles]
        for wk in weeks:
            if others and rng.random() < a["unplanned_work_probability"]:
                rows.append(_actual(pid, pick(rng, others), wk, rng.uniform(4, 16)))
    unique = {(r["project_id"], r["role_id"], r["week_start_date"]): r for r in rows}
    return [unique[k] for k in sorted(unique)]


def _actual(pid: str, rid: str, wk: date, value: float) -> Row:
    iso = iso_week_of(wk)
    return {
        "project_id": pid,
        "role_id": rid,
        "week_start_date": wk,
        "iso_year": iso.year,
        "iso_week": iso.week,
        "actual_hours": max(0.0, round_half(value)),
        "source": "SYNTHETIC_TIMESHEET",
    }


def allocation_ids(rows: list[Row], start_seq: int = 1) -> None:
    rows.sort(key=lambda r: (r["start_date"], r["employee_id"], r["project_id"], r["role_id"]))
    for seq, r in enumerate(rows, start_seq):
        r["allocation_id"] = format_id(EntityKind.ALLOCATION, seq, year=r["start_date"].year)

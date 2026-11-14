"""Inject the four labelled anomaly types into the clean baseline (docs/06 section 6).

Every injected record is structurally valid (keys, enums, CHECKs). Expected outcomes in the
ground truth are computed from the records with the documented rules, never assigned at
random. Each anomaly type targets different employees so the types stay separable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from app.domain.calendar import iso_week_of
from app.domain.ids import EntityKind, demand_id, format_id, sequence_of
from datagen.capacity import CapacityModel, WeekCapacity, group_by
from datagen.config import GeneratorConfig
from datagen.rng import pick, round_half, stage_rng

Row = dict[str, Any]
OVERALLOCATION = "ALLOCATION_EXCEEDS_AVAILABILITY"
EXPIRED = "EXPIRED_SKILL_TREATED_AS_CURRENT"
DUPLICATE = "DUPLICATE_DEMAND"
CONFLICT = "OVERLAPPING_ALLOCATION_CONFLICT"
ANOMALY_TYPES = (OVERALLOCATION, EXPIRED, DUPLICATE, CONFLICT)
RULE = {
    OVERALLOCATION: "BR-UTL-004",
    EXPIRED: "BR-SKL-004",
    DUPLICATE: "BR-DEM-004",
    CONFLICT: "BR-ALC-003",
}
UNIT = {
    OVERALLOCATION: "EMPLOYEE_WEEK",
    EXPIRED: "EMPLOYEE_SKILL",
    DUPLICATE: "DEMAND_LINE",
    CONFLICT: "ALLOCATION_PAIR",
}
CONFIG_KEY = {
    OVERALLOCATION: "allocation_exceeds_availability",
    EXPIRED: "expired_skill_treated_as_current",
    DUPLICATE: "duplicate_demand",
    CONFLICT: "overlapping_allocation_conflict",
}
ACTIVE_PROJECT = {"APPROVED", "ACTIVE"}


class Injector:
    def __init__(self, cfg: GeneratorConfig, tables: dict[str, list[Row]]) -> None:
        self.cfg = cfg
        self.t = tables
        self.model = CapacityModel(cfg)
        self.rng = stage_rng(cfg.seed, "anomalies")
        self.used: set[str] = set()
        self.ground_truth: list[Row] = []
        self.employees = {e["employee_id"]: e for e in tables["employee"]}
        self.index = {
            name: group_by(tables[name], "employee_id")
            for name in ("availability", "training", "allocation")
        }
        self.next_seq = {
            EntityKind.ALLOCATION: max(
                sequence_of(EntityKind.ALLOCATION, r["allocation_id"]) for r in tables["allocation"]
            )
            + 1,
            EntityKind.AVAILABILITY: max(
                sequence_of(EntityKind.AVAILABILITY, r["availability_id"])
                for r in tables["availability"]
            )
            + 1,
        }

    # ------------------------------------------------------------------ helpers
    def _new_id(self, kind: EntityKind, start: date) -> str:
        seq = self.next_seq[kind]
        self.next_seq[kind] += 1
        return format_id(kind, seq, year=start.year)

    def _add(self, table: str, row: Row) -> None:
        self.t[table].append(row)
        self.index[table].setdefault(row["employee_id"], []).append(row)

    def _remove(self, table: str, row: Row) -> None:
        self.t[table].remove(row)
        self.index[table][row["employee_id"]].remove(row)

    def _rows(self, table: str, employee_id: str) -> list[Row]:
        return self.index[table].get(employee_id, [])

    def capacity(self, employee_id: str) -> WeekCapacity:
        return self.model.compute(
            self.employees[employee_id],
            self._rows("availability", employee_id),
            self._rows("training", employee_id),
            self._rows("allocation", employee_id),
        )

    def _gt(
        self,
        event: str,
        kind: str,
        key: str,
        primary: tuple[str, str],
        sources: list[str],
        week: date | None,
        method: str,
        outcome: str,
    ) -> None:
        self.ground_truth.append(
            {
                "injection_event": event,
                "anomaly_type": kind,
                "rule_id": RULE[kind],
                "evaluation_unit": UNIT[kind],
                "evaluation_key": key,
                "primary_record_type": primary[0],
                "primary_record_id": primary[1],
                "source_record_ids": "|".join(sorted(set(sources))),
                "week_start_date": week,
                "injection_method": method,
                "expected_outcome": outcome,
            }
        )

    def _candidates[T](self, rows: Sequence[T]) -> list[T]:
        return [rows[int(i)] for i in self.rng.permutation(len(rows))]

    def _employee_ok(self, employee_id: str) -> bool:
        e = self.employees[employee_id]
        return (
            employee_id not in self.used
            and e["status"] == "ACTIVE"
            and e["termination_date"] is None
        )

    def _project_covering(self, first: date, last: date, exclude: str | None) -> Row | None:
        options = [
            p
            for p in self.t["project"]
            if p["status"] in ACTIVE_PROJECT
            and p["start_date"] <= first
            and p["end_date"] >= last
            and p["project_id"] != exclude
        ]
        return pick(self.rng, options) if options else None

    def _overallocated_weeks(self, employee_id: str) -> list[int]:
        cap = self.capacity(employee_id)
        return [
            int(w)
            for w in range(self.cfg.horizon_weeks)
            if cap.allocated[w] > cap.net[w] + self.model.tolerance
        ]

    def _record_overallocation(
        self, event: str, employee_id: str, primary: tuple[str, str], method: str
    ) -> bool:
        cap = self.capacity(employee_id)
        weeks = self._overallocated_weeks(employee_id)
        for w in weeks:
            monday = self.cfg.weeks[w]
            sunday = monday + timedelta(days=6)
            overlapping = [
                a["allocation_id"]
                for a in self._rows("allocation", employee_id)
                if a["status"] in self.model.alloc_statuses
                and a["start_date"] <= sunday
                and a["end_date"] >= monday
            ]
            self._gt(
                event,
                OVERALLOCATION,
                f"{employee_id}|{monday.isoformat()}",
                primary,
                [primary[1], *overlapping],
                monday,
                method,
                f"{OVERALLOCATION} for {employee_id} in {iso_week_of(monday).label}: "
                f"allocated {cap.allocated[w]:.2f} h > net available {cap.net[w]:.2f} h",
            )
        return bool(weeks)

    # ------------------------------------------------------------------ 1. over-allocation
    def overallocation(self, count: int) -> None:
        methods = ("LEAVE_AFTER_STAFFING", "HOURS_INCREASED", "PART_TIMER_OVERBOOKED")
        allocs = group_by(self.t["allocation"], "employee_id")
        candidates = [
            eid
            for eid in self._candidates(sorted(allocs))
            if self._employee_ok(eid)
            and all(a["allocation_type"] == "SHARED" for a in allocs[eid])
            and any(a["status"] == "CONFIRMED" for a in allocs[eid])
        ]
        for n in range(1, count + 1):
            event = f"INJ-OVA-{n:03d}"
            for method in (methods[(n - 1) % 3], *methods):
                done = next(
                    (
                        eid
                        for eid in candidates
                        if eid not in self.used
                        and getattr(self, f"_ova_{method.lower()}")(event, eid)
                    ),
                    None,
                )
                if done:
                    self.used.add(done)
                    break
            else:
                raise RuntimeError(f"could not inject {OVERALLOCATION} event {n}")

    def _ova_leave_after_staffing(self, event: str, eid: str) -> bool:
        cap = self.capacity(eid)
        weeks = [
            w
            for w in range(self.cfg.horizon_weeks)
            if cap.gross[w] > 0
            and cap.leave[w] == 0
            and cap.training[w] == 0
            and cap.allocated[w] >= 0.5 * cap.gross[w]
            and self.model.span(self.cfg.weeks[w], self.cfg.weeks[w]) is not None
        ]
        if not weeks:
            return False
        monday = self.cfg.weeks[pick(self.rng, weeks)]
        if self.employees[eid]["hire_date"] > monday:
            return False
        leave: Row = {
            "availability_id": self._new_id(EntityKind.AVAILABILITY, monday),
            "employee_id": eid,
            "availability_type": "ANNUAL_LEAVE",
            "start_date": monday,
            "end_date": monday + timedelta(days=4),
            "weekly_hours": None,
            "hours_per_day": None,
            "status": "APPROVED",
            "reason": None,  # no tell-tale text (label leakage)
        }
        self._add("availability", leave)
        return self._record_overallocation(
            event, eid, ("availability", leave["availability_id"]), "LEAVE_AFTER_STAFFING"
        )

    def _ova_hours_increased(self, event: str, eid: str) -> bool:
        cap = self.capacity(eid)
        options = [
            a
            for a in self._rows("allocation", eid)
            if a["status"] == "CONFIRMED" and a["allocation_type"] == "SHARED"
        ]
        if not options:
            return False
        alloc = min(options, key=lambda a: (a["end_date"] - a["start_date"], a["allocation_id"]))
        sl = self.model.span(alloc["start_date"], alloc["end_date"])
        if sl is None:
            return False
        weeks = range(sl.start // 7, (sl.stop - 1) // 7 + 1)
        delta = round_half(max(float(cap.free[w]) for w in weeks) + self.rng.uniform(4, 12))
        new_hours = alloc["hours_per_week"] + delta
        if new_hours > 60:
            return False
        alloc["hours_per_week"] = new_hours
        return self._record_overallocation(
            event, eid, ("allocation", alloc["allocation_id"]), "HOURS_INCREASED"
        )

    def _ova_part_timer_overbooked(self, event: str, eid: str) -> bool:
        schedule = [
            a for a in self._rows("availability", eid) if a["availability_type"] == "WORK_SCHEDULE"
        ]
        if not any(float(s["weekly_hours"]) < 40 for s in schedule):
            return False
        cap = self.capacity(eid)
        full = [
            w
            for w in range(self.cfg.horizon_weeks - 1)
            if cap.gross[w] > 0 and cap.gross[w + 1] > 0 and cap.gross[w] < 40
        ]
        if not full:
            return False
        w = pick(self.rng, full)
        first, last = self.cfg.weeks[w], self.cfg.weeks[w + 1] + timedelta(days=6)
        project = self._project_covering(first, last, exclude=None)
        if project is None:
            return False
        hours = round_half(
            max(float(cap.free[w]), float(cap.free[w + 1])) + self.rng.uniform(4, 12)
        )
        if hours > 60:
            return False
        alloc: Row = {
            "allocation_id": self._new_id(EntityKind.ALLOCATION, first),
            "employee_id": eid,
            "project_id": project["project_id"],
            "role_id": self.employees[eid]["role_id"],
            "start_date": first,
            "end_date": last,
            "hours_per_week": hours,
            "allocation_type": "SHARED",
            "status": "CONFIRMED",
            "notes": None,
        }
        self._add("allocation", alloc)
        return self._record_overallocation(
            event, eid, ("allocation", alloc["allocation_id"]), "PART_TIMER_OVERBOOKED"
        )

    # ------------------------------------------------------------------ 2. expired skill
    def expired_skills(self, count: int) -> None:
        cert = {s["skill_id"] for s in self.t["skill"] if s["requires_certification"]}
        as_of = self.cfg.as_of
        rows = [
            v
            for v in self.t["employee_skill"]
            if v["effective_to"] is None
            and v["skill_id"] in cert
            and v["recorded_status"] == "CURRENT"
            and v["expiry_date"] >= as_of
            and v["last_verified_date"] <= as_of - timedelta(days=200)
        ]
        done = 0
        for v in self._candidates(rows):
            if done == count:
                break
            if not self._employee_ok(v["employee_id"]):
                continue
            v["expiry_date"] = as_of - timedelta(days=int(self.rng.integers(1, 181)))
            done += 1
            self.used.add(v["employee_id"])
            self._gt(
                f"INJ-EXP-{done:03d}",
                EXPIRED,
                v["employee_skill_id"],
                ("employee_skill", v["employee_skill_id"]),
                [v["employee_skill_id"], v["employee_id"], v["skill_id"]],
                None,
                "EXPIRY_PASSED_FLAG_NOT_UPDATED",
                f"{EXPIRED} for {v['employee_skill_id']}: expiry_date "
                f"{v['expiry_date'].isoformat()} < as_of {as_of.isoformat()} while "
                "recorded_status = CURRENT; employee not eligible for that skill",
            )
        if done < count:
            raise RuntimeError(f"only {done} of {count} {EXPIRED} candidates")

    # ------------------------------------------------------------------ 3. duplicate demand
    def duplicate_demand(self, count: int) -> None:
        status = {p["project_id"]: p["status"] for p in self.t["project"]}
        primary = {
            r["demand_id"]: r
            for r in self.t["demand_skill_requirement"]
            if r["requirement_type"] == "PRIMARY"
        }
        reqs = group_by(self.t["demand_skill_requirement"], "demand_id")
        max_line: dict[tuple[str, date], int] = {}
        for line in self.t["demand_plan"]:
            k = (line["project_id"], line["week_start_date"])
            max_line[k] = max(max_line.get(k, 0), line["line_no"])
        counted = [
            line
            for line in self.t["demand_plan"]
            if line["status"] in ("SUBMITTED", "APPROVED")
            and status[line["project_id"]] in ACTIVE_PROJECT
        ]
        seen_projects: set[str] = set()
        done = 0
        for line in self._candidates(counted):
            if done == count:
                break
            if line["project_id"] in seen_projects and len(seen_projects) < len(status):
                continue
            k = (line["project_id"], line["week_start_date"])
            if max_line[k] >= 99:
                continue
            max_line[k] += 1
            iso = iso_week_of(line["week_start_date"])
            new_id = demand_id(line["project_id"], iso.year, iso.week, max_line[k])
            exact = self.rng.random() < 0.5
            hours = (
                line["required_hours"]
                if exact
                else max(1.0, round_half(line["required_hours"] * self.rng.uniform(0.9, 1.1)))
            )
            self.t["demand_plan"].append(
                line
                | {
                    "demand_id": new_id,
                    "line_no": max_line[k],
                    "required_hours": hours,
                    "headcount": max(1, math.ceil(hours / 40)),
                }
            )
            self.t["demand_skill_requirement"] += [
                r | {"demand_id": new_id} for r in reqs[line["demand_id"]]
            ]
            seen_projects.add(line["project_id"])
            done += 1
            self._gt(
                f"INJ-DUP-{done:03d}",
                DUPLICATE,
                new_id,
                ("demand_plan", new_id),
                [line["demand_id"], new_id],
                line["week_start_date"],
                "EXACT_COPY" if exact else "COPY_WITH_HOURS_CHANGED",
                f"{DUPLICATE}: {new_id} repeats {line['demand_id']} (same project, week, "
                f"role {line['role_id']}, primary skill {primary[line['demand_id']]['skill_id']}"
                f", min proficiency {primary[line['demand_id']]['min_proficiency']}); the "
                "duplicate is excluded from demand totals",
            )
        if done < count:
            raise RuntimeError(f"only {done} of {count} {DUPLICATE} candidates")

    # ------------------------------------------------------------------ 4. conflict
    def conflicts(self, count: int) -> None:
        dedicated = [
            a
            for a in self.t["allocation"]
            if a["allocation_type"] == "DEDICATED" and a["status"] == "CONFIRMED"
        ]
        done = 0
        for ded in self._candidates(dedicated):
            if done == count:
                break
            eid = ded["employee_id"]
            if not self._employee_ok(eid):
                continue
            cap = self.capacity(eid)
            windows = []
            for w in range(self.cfg.horizon_weeks - 1):
                first, last = self.cfg.weeks[w], self.cfg.weeks[w + 1] + timedelta(days=6)
                if ded["start_date"] <= first and ded["end_date"] >= last:
                    slack = min(float(cap.free[w]), float(cap.free[w + 1]))
                    if slack >= 4:
                        windows.append((w, slack))
            if not windows:
                continue
            w, slack = windows[int(self.rng.integers(len(windows)))]
            first, last = self.cfg.weeks[w], self.cfg.weeks[w + 1] + timedelta(days=6)
            project = self._project_covering(first, last, exclude=ded["project_id"])
            if project is None:
                continue
            hours = min(16.0, math.floor(slack * 2) / 2)
            new: Row = {
                "allocation_id": self._new_id(EntityKind.ALLOCATION, first),
                "employee_id": eid,
                "project_id": project["project_id"],
                "role_id": self.employees[eid]["role_id"],
                "start_date": first,
                "end_date": last,
                "hours_per_week": hours,
                "allocation_type": "SHARED",
                "status": "CONFIRMED",
                "notes": None,
            }
            self._add("allocation", new)
            if self._overallocated_weeks(eid):  # must stay a pure exclusivity conflict
                self._remove("allocation", new)
                continue
            self.used.add(eid)
            done += 1
            pair = sorted([ded["allocation_id"], new["allocation_id"]])
            self._gt(
                f"INJ-CON-{done:03d}",
                CONFLICT,
                "|".join(pair),
                ("allocation", new["allocation_id"]),
                pair,
                first,
                "SHARED_OVER_DEDICATED",
                f"{CONFLICT}: {new['allocation_id']} ({first}..{last}) overlaps DEDICATED "
                f"{ded['allocation_id']} of {eid}; hours fit capacity, so no over-allocation",
            )
        if done < count:
            raise RuntimeError(f"only {done} of {count} {CONFLICT} candidates")


def inject_anomalies(cfg: GeneratorConfig, tables: dict[str, list[Row]]) -> list[Row]:
    injector = Injector(cfg, tables)
    injector.overallocation(cfg.anomalies[CONFIG_KEY[OVERALLOCATION]])
    injector.expired_skills(cfg.anomalies[CONFIG_KEY[EXPIRED]])
    injector.duplicate_demand(cfg.anomalies[CONFIG_KEY[DUPLICATE]])
    injector.conflicts(cfg.anomalies[CONFIG_KEY[CONFLICT]])
    order = {t: i for i, t in enumerate(ANOMALY_TYPES)}
    gt = sorted(
        injector.ground_truth, key=lambda r: (order[r["anomaly_type"]], r["evaluation_key"])
    )
    for i, row in enumerate(gt, 1):
        row["gt_id"] = format_id(EntityKind.GROUND_TRUTH, i)
    return gt

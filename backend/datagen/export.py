"""Deterministic exports: CSV, JSON, SQL seed, ground truth, derived facts and the manifest.

Determinism: rows sorted by primary key, columns in model order, fixed number formatting,
UTF-8, LF line endings, JSON with sorted keys. No timestamps of the generation run are written.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import platform
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import Table

from app.db.registry import metadata
from app.db.types import DecimalType
from datagen.capacity import CapacityModel, WeekCapacity
from datagen.checks import counted_demand, duplicate_lines
from datagen.config import GeneratorConfig
from datagen.master import effective_status

Row = dict[str, Any]
GT_COLUMNS = (
    "gt_id",
    "injection_event",
    "anomaly_type",
    "rule_id",
    "evaluation_unit",
    "evaluation_key",
    "primary_record_type",
    "primary_record_id",
    "source_record_ids",
    "week_start_date",
    "injection_method",
    "expected_outcome",
)


def input_tables(tables: dict[str, list[Row]]) -> list[Table]:
    """Exported tables in foreign-key order (parents first)."""
    return [t for t in metadata.sorted_tables if tables.get(t.name)]


def sorted_rows(table: Table, rows: list[Row]) -> list[Row]:
    pk = [c.name for c in table.primary_key.columns]
    return sorted(rows, key=lambda r: tuple(r[c] for c in pk))


# ------------------------------------------------------------------ value formatting
def _text(value: Any, scale: int | None = None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if scale is not None:
        return f"{float(value):.{scale}f}"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _json(value: Any, scale: int | None = None) -> Any:
    if value is None or isinstance(value, bool | str | int):
        return value
    if scale is not None:
        return round(float(value), scale)
    if isinstance(value, datetime | date):
        return _text(value)
    if isinstance(value, float):
        return value
    return str(value)


def _sql(value: Any, scale: int | None = None) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if scale is not None:
        return f"{float(value):.{scale}f}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, datetime):
        return "'" + value.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(value, date):
        return f"'{value.isoformat()}'"
    return "'" + str(value).replace("'", "''") + "'"


def _scales(table: Table) -> dict[str, int | None]:
    return {
        c.name: (c.type.scale if isinstance(c.type, DecimalType) else None) for c in table.columns
    }


# ------------------------------------------------------------------ writers
def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def csv_text(columns: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return buf.getvalue()


def json_text(records: Iterable[dict[str, Any]]) -> str:
    lines = [
        json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for r in records
    ]
    return "[\n" + ",\n".join(lines) + "\n]\n" if lines else "[]\n"


def write_inputs(out: Path, tables: dict[str, list[Row]]) -> None:
    sql = [
        "-- WorkforceIQ synthetic seed data (generated; do not edit).",
        "-- Load into a database migrated to Alembic head that contains no dataset rows.",
        "BEGIN;",
    ]
    for table in input_tables(tables):
        cols = [c.name for c in table.columns]
        scales = _scales(table)
        rows = sorted_rows(table, tables[table.name])
        _write(
            out / "csv" / f"{table.name}.csv",
            csv_text(cols, ([_text(r[c], scales[c]) for c in cols] for r in rows)),
        )
        _write(
            out / "json" / f"{table.name}.json",
            json_text({c: _json(r[c], scales[c]) for c in cols} for r in rows),
        )
        for start in range(0, len(rows), 500):
            values = ",\n".join(
                "(" + ", ".join(_sql(r[c], scales[c]) for c in cols) + ")"
                for r in rows[start : start + 500]
            )
            sql.append(f"INSERT INTO {table.name} ({', '.join(cols)}) VALUES\n{values};")
    sql.append("COMMIT;")
    _write(out / "sql" / "seed.sql", "\n".join(sql) + "\n")


def write_ground_truth(out: Path, ground_truth: list[Row]) -> None:
    rows = [[_text(g[c]) for c in GT_COLUMNS] for g in ground_truth]
    _write(out / "ground_truth" / "ground_truth.csv", csv_text(GT_COLUMNS, rows))
    _write(
        out / "ground_truth" / "ground_truth.json",
        json_text({c: _json(g[c]) for c in GT_COLUMNS} for g in ground_truth),
    )


# ------------------------------------------------------------------ derived facts
def write_derived(
    out: Path, cfg: GeneratorConfig, tables: dict[str, list[Row]], capacity: dict[str, WeekCapacity]
) -> dict[str, Any]:
    """Capacity, utilization, demand totals, skill eligibility and coarse gaps, all computed
    from the records (inputs for later phases' cross-checks; contain no anomaly labels)."""
    weeks = cfg.weeks
    rows = []
    for eid in sorted(capacity):
        cap = capacity[eid]
        for w, monday in enumerate(weeks):
            net, alloc = float(cap.net[w]), float(cap.allocated[w])
            util = f"{alloc / net:.4f}" if net > 0 else ""
            rows.append(
                [
                    eid,
                    monday.isoformat(),
                    *(
                        f"{float(x[w]):.2f}"
                        for x in (
                            cap.gross,
                            cap.leave,
                            cap.training,
                            cap.net,
                            cap.allocated,
                            cap.free,
                        )
                    ),
                    util,
                ]
            )
    _write(
        out / "derived" / "capacity_weekly.csv",
        csv_text(
            (
                "employee_id",
                "week_start_date",
                "gross_hours",
                "leave_hours",
                "training_hours",
                "net_hours",
                "allocated_hours",
                "free_hours",
                "utilization",
            ),
            rows,
        ),
    )

    # Planned demand over the whole horizon: submitted/approved lines, de-duplicated
    # (BR-DEM-004). BR-DEM-003 (forward-looking: active projects only) is reported separately.
    dups, _ = duplicate_lines(cfg, tables)
    statuses = set(cfg.rule("BR-DEM-003", "counted_demand_statuses"))
    planned = [
        d for d in tables["demand_plan"] if d["status"] in statuses and d["demand_id"] not in dups
    ]
    counted_hours = sum(
        d["required_hours"] for d in counted_demand(cfg, tables) if d["demand_id"] not in dups
    )
    demand = np.zeros((len(tables["role"]), len(weeks)))
    role_idx = {r["role_id"]: i for i, r in enumerate(tables["role"])}
    week_idx = {m: i for i, m in enumerate(weeks)}
    for d in planned:
        demand[role_idx[d["role_id"]], week_idx[d["week_start_date"]]] += d["required_hours"]
    supply = np.zeros_like(demand)
    allocated = np.zeros_like(demand)
    for e in tables["employee"]:
        supply[role_idx[e["role_id"]]] += capacity[e["employee_id"]].net
    model = CapacityModel(cfg)
    for a in tables["allocation"]:
        sl = model.span(a["start_date"], a["end_date"])
        if a["status"] in model.alloc_statuses and sl is not None:
            for w in range(sl.start // 7, (sl.stop - 1) // 7 + 1):
                allocated[role_idx[a["role_id"]], w] += model.prorated_hours(
                    a["hours_per_week"], a["start_date"], a["end_date"], weeks[w]
                )
    balance = []
    for r in tables["role"]:
        i = role_idx[r["role_id"]]
        for w, monday in enumerate(weeks):
            gap = max(0.0, demand[i, w] - supply[i, w])
            balance.append(
                [
                    r["role_id"],
                    monday.isoformat(),
                    f"{demand[i, w]:.2f}",
                    f"{supply[i, w]:.2f}",
                    f"{allocated[i, w]:.2f}",
                    f"{gap:.2f}",
                ]
            )
    _write(
        out / "derived" / "role_week_balance.csv",
        csv_text(
            (
                "role_id",
                "week_start_date",
                "demand_hours",
                "supply_net_hours",
                "allocated_hours",
                "gap_hours",
            ),
            balance,
        ),
    )

    # skill eligibility at as_of (BR-SKL-002/006: VALID and proficiency >= default minimum)
    freshness = int(cfg.rule("BR-SKL-002", "freshness_days"))
    min_level = int(cfg.rule("BR-SKL-006", "default_min_proficiency"))
    active = {e["employee_id"] for e in tables["employee"] if e["status"] == "ACTIVE"}
    primary = {
        r["demand_id"]: r["skill_id"]
        for r in tables["demand_skill_requirement"]
        if r["requirement_type"] == "PRIMARY"
    }
    skill_demand: dict[str, float] = {}
    for d in planned:
        skill_demand[primary[d["demand_id"]]] = (
            skill_demand.get(primary[d["demand_id"]], 0.0) + d["required_hours"]
        )
    status_counts: dict[str, dict[str, int]] = {s["skill_id"]: {} for s in tables["skill"]}
    for v in tables["employee_skill"]:
        if v["effective_to"] is None and v["employee_id"] in active:
            st = effective_status(v, cfg.as_of, freshness)
            if st == "VALID" and v["proficiency_level"] < min_level:
                st = "VALID_BELOW_MIN"
            status_counts[v["skill_id"]][st] = status_counts[v["skill_id"]].get(st, 0) + 1
    eligibility = [
        [
            sid,
            f"{skill_demand.get(sid, 0.0):.2f}",
            *(
                str(c.get(k, 0))
                for k in ("VALID", "VALID_BELOW_MIN", "STALE", "PENDING", "EXPIRED")
            ),
        ]
        for sid, c in sorted(status_counts.items())
    ]
    _write(
        out / "derived" / "skill_eligibility.csv",
        csv_text(
            (
                "skill_id",
                "planned_primary_demand_hours",
                "eligible_employees",
                "valid_below_min",
                "stale",
                "pending",
                "expired",
            ),
            eligibility,
        ),
    )

    net_total = float(sum(c.net.sum() for c in capacity.values()))
    alloc_total = float(sum(c.allocated.sum() for c in capacity.values()))
    return {
        "total_gross_hours": round(float(sum(c.gross.sum() for c in capacity.values())), 2),
        "total_net_hours": round(net_total, 2),
        "total_allocated_hours": round(alloc_total, 2),
        "utilization_hours_weighted": round(alloc_total / net_total, 4) if net_total else None,
        "planned_demand_hours_dedup": round(float(demand.sum()), 2),
        "counted_demand_hours_br_dem_003": round(counted_hours, 2),
        "demand_to_net_capacity": round(float(demand.sum()) / net_total, 4) if net_total else None,
        "role_week_gap_hours": round(float(sum(float(b[5]) for b in balance)), 2),
        "skills_without_eligible_employees": sum(1 for row in eligibility if row[2] == "0"),
    }


# ------------------------------------------------------------------ manifest
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_manifest(out: Path, skip: Iterable[str] = ("manifest.json",)) -> dict[str, Any]:
    entries = {}
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p.name not in set(skip)):
        rel = path.relative_to(out).as_posix()
        data = path.read_bytes()
        rows = data.count(b"\n") - 1 if path.suffix == ".csv" else None
        if path.suffix == ".json" and data.startswith(b"["):
            rows = len(json.loads(data))
        entries[rel] = {
            "bytes": len(data),
            "rows": rows,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return entries


def write_manifest(
    out: Path, cfg: GeneratorConfig, tables: dict[str, list[Row]], ground_truth: list[Row]
) -> dict[str, Any]:
    events: dict[str, set[str]] = {}
    for g in ground_truth:
        events.setdefault(g["anomaly_type"], set()).add(g["injection_event"])
    manifest = {
        "dataset": {
            "mode": cfg.mode,
            "seed": cfg.seed,
            "generator_version": cfg.generator_version,
            "as_of_date": cfg.as_of.isoformat(),
            "horizon_start": cfg.horizon_start.isoformat(),
            "horizon_end": cfg.horizon_end.isoformat(),
            "horizon_weeks": cfg.horizon_weeks,
            "holdout_weeks": cfg.holdout_weeks,
            "config_sha256": cfg.config_sha256,
            "rules_version": cfg.rules.version,
            "rules_sha256": cfg.rules.sha256,
        },
        "provenance": {
            "data": "Fully synthetic. No real people, companies or external datasets.",
            "sources": [
                "Author-written role/skill taxonomy (datagen/vocabulary.py)",
                f"Faker {version('faker')} (MIT licence) for names, cities and company names",
                f"NumPy {version('numpy')} PCG64 random streams, one per stage, seeded from "
                "SHA-256(seed:stage)",
            ],
            "python": platform.python_version().rsplit(".", 1)[0],
            "reproducibility": "Same seed + config + code + library versions => identical files",
        },
        "tables": {t.name: len(tables[t.name]) for t in input_tables(tables)},
        "anomalies": {
            t: {
                "events": len(e),
                "ground_truth_rows": sum(1 for g in ground_truth if g["anomaly_type"] == t),
            }
            for t, e in sorted(events.items())
        },
        "files": file_manifest(out),
    }
    _write(out / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest

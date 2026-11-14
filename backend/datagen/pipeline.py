"""Generation pipeline: master data -> dependent data -> baseline check -> anomalies ->
validation -> exports -> optional database load (docs/06 section 2)."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

from app.core.config import REPO_ROOT
from app.domain.ids import ID_FORMATS, EntityKind, sequence_of
from datagen import anomalies, export, master, workload
from datagen.capacity import capacity_by_employee
from datagen.checks import Check, summarize, validate
from datagen.config import GeneratorConfig, load_config

Row = dict[str, Any]
OUTPUT_ROOT = REPO_ROOT / "data" / "generated"
SEQUENCED = {
    "employee": ("employee_id", EntityKind.EMPLOYEE),
    "role": ("role_id", EntityKind.ROLE),
    "skill": ("skill_id", EntityKind.SKILL),
    "employee_skill": ("employee_skill_id", EntityKind.EMPLOYEE_SKILL),
    "project": ("project_id", EntityKind.PROJECT),
    "allocation": ("allocation_id", EntityKind.ALLOCATION),
    "availability": ("availability_id", EntityKind.AVAILABILITY),
    "training": ("training_id", EntityKind.TRAINING),
}


@dataclass
class Dataset:
    config: GeneratorConfig
    tables: dict[str, list[Row]]
    ground_truth: list[Row]
    baseline_checks: list[Check]
    checks: list[Check]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.baseline_checks + self.checks)


def generate(cfg: GeneratorConfig) -> Dataset:
    roles = master.build_roles(cfg)
    skills = master.build_skills(cfg)
    role_skills = master.build_role_skills(cfg, roles, skills)
    employees = master.build_employees(cfg, roles)
    availability = master.build_schedules(cfg, employees) + master.build_leave(cfg, employees)
    master.assign_year_ids(
        availability,
        EntityKind.AVAILABILITY,
        "availability_id",
        ("employee_id", "start_date", "availability_type", "end_date"),
    )
    versions, past_trainings = master.build_employee_skills(
        cfg, roles, employees, role_skills, skills
    )
    trainings = past_trainings + master.build_horizon_trainings(
        cfg, employees, role_skills, versions, skills
    )
    master.assign_year_ids(
        trainings, EntityKind.TRAINING, "training_id", ("start_date", "employee_id", "skill_id")
    )
    tables: dict[str, list[Row]] = {
        "role": roles,
        "skill": skills,
        "role_skill": role_skills,
        "employee": employees,
        "availability": availability,
        "employee_skill": versions,
        "training": trainings,
    }

    capacity = capacity_by_employee(cfg, tables)  # before allocations: net capacity
    projects = workload.build_projects(cfg)
    groups = workload.build_demand_groups(cfg, projects, roles, role_skills)
    role_net: dict[str, float] = {}
    for e in employees:
        role_net[e["role_id"]] = role_net.get(e["role_id"], 0.0) + float(
            capacity[e["employee_id"]].net.sum()
        )
    workload.scale_demand(cfg, groups, role_net)
    lines, requirements = workload.build_demand_lines(cfg, groups)
    current = {(v["employee_id"], v["skill_id"]): v for v in versions if v["effective_to"] is None}
    allocations = workload.build_allocations(cfg, groups, employees, capacity, current, roles)
    workload.allocation_ids(allocations)
    tables |= {
        "project": projects,
        "demand_plan": lines,
        "demand_skill_requirement": requirements,
        "allocation": allocations,
        "demand_actual": workload.build_actuals(cfg, lines, projects, roles),
    }

    baseline_checks = validate(cfg, tables, capacity_by_employee(cfg, tables), None)
    if not all(c.passed for c in baseline_checks):
        failed = [c for c in baseline_checks if not c.passed]
        raise RuntimeError(f"baseline validation failed: {failed}")

    ground_truth = anomalies.inject_anomalies(cfg, tables)
    _renumber(tables, ground_truth)
    _finalize(cfg, tables)
    checks = validate(cfg, tables, capacity_by_employee(cfg, tables), ground_truth)
    return Dataset(cfg, tables, ground_truth, baseline_checks, checks)


_ID_TOKEN = re.compile(r"\b(?:ALLOC|AVL)-\d{4}-\d{6}\b")


def _renumber(tables: dict[str, list[Row]], ground_truth: list[Row]) -> None:
    """Re-assign allocation and availability IDs over baseline + injected rows together, so
    injected records do not stand out by having the highest IDs (label leakage)."""
    mapping: dict[str, str] = {}
    for name, col, kind, sort_cols in (
        ("allocation", "allocation_id", EntityKind.ALLOCATION, ()),
        (
            "availability",
            "availability_id",
            EntityKind.AVAILABILITY,
            ("employee_id", "start_date", "availability_type", "end_date"),
        ),
    ):
        for r in tables[name]:
            r["_old"] = r[col]
        if kind is EntityKind.ALLOCATION:
            workload.allocation_ids(tables[name])
        else:
            master.assign_year_ids(tables[name], kind, col, sort_cols)
        for r in tables[name]:
            mapping[r.pop("_old")] = r[col]

    def remap(text: str) -> str:
        return _ID_TOKEN.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)

    for g in ground_truth:
        for field in ("primary_record_id", "expected_outcome"):
            g[field] = remap(g[field])
        g["source_record_ids"] = "|".join(
            sorted(remap(s) for s in g["source_record_ids"].split("|"))
        )
        if g["evaluation_unit"] == "ALLOCATION_PAIR":
            g["evaluation_key"] = "|".join(sorted(remap(k) for k in g["evaluation_key"].split("|")))


def _finalize(cfg: GeneratorConfig, tables: dict[str, list[Row]]) -> None:
    """Deterministic audit timestamps, ID sequences and dataset metadata."""
    stamp = datetime.combine(cfg.as_of, time(0, 0), tzinfo=UTC)
    from app.db.registry import metadata

    for name, rows in tables.items():
        if "created_at" in metadata.tables[name].columns:
            for r in rows:
                r["created_at"] = r["updated_at"] = stamp
    tables["id_sequence"] = [
        {
            "prefix": ID_FORMATS[kind].prefix,
            "last_value": max(sequence_of(kind, r[col]) for r in tables[name]),
        }
        for name, (col, kind) in sorted(SEQUENCED.items())
    ]
    meta = {
        "mode": cfg.mode,
        "seed": str(cfg.seed),
        "generator_version": cfg.generator_version,
        "as_of_date": cfg.as_of.isoformat(),
        "horizon_start": cfg.horizon_start.isoformat(),
        "horizon_end": cfg.horizon_end.isoformat(),
        "horizon_weeks": str(cfg.horizon_weeks),
        "holdout_weeks": str(cfg.holdout_weeks),
        "config_sha256": cfg.config_sha256,
        "rules_version": cfg.rules.version,
        "rules_sha256": cfg.rules.sha256,
    }
    tables["dataset_metadata"] = [{"key": k, "value": v} for k, v in sorted(meta.items())]


def write_outputs(ds: Dataset, out: Path) -> dict[str, Any]:
    """Write everything into ``out`` (replaced atomically-ish via a sibling temp folder)."""
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        export.write_inputs(tmp, ds.tables)
        export.write_ground_truth(tmp, ds.ground_truth)
        derived = export.write_derived(
            tmp, ds.config, ds.tables, capacity_by_employee(ds.config, ds.tables)
        )
        summary = {
            "passed": ds.passed,
            "baseline_checks": summarize(ds.baseline_checks),
            "checks": summarize(ds.checks),
            "derived": derived,
        }
        export._write(
            tmp / "validation_summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n"
        )
        manifest = export.write_manifest(tmp, ds.config, ds.tables, ds.ground_truth)
        if out.exists():
            shutil.rmtree(out)  # only this mode's generated folder
        tmp.rename(out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return manifest


def run(
    mode: str, *, seed: int | None = None, out_root: Path = OUTPUT_ROOT
) -> tuple[Dataset, dict[str, Any]]:
    ds = generate(load_config(mode, seed=seed))
    if not ds.passed:
        failed = [c for c in ds.checks if not c.passed]
        raise RuntimeError(f"validation failed: {failed}")
    return ds, write_outputs(ds, out_root / mode)


def compare_runs(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Compare two manifests: identical row counts and SHA-256 for every file."""
    a, b = first["files"], second["files"]
    differing = sorted(f for f in set(a) | set(b) if a.get(f) != b.get(f))
    return {
        "identical": not differing and first == second,
        "files_compared": len(set(a) | set(b)),
        "rows_compared": sum(v["rows"] or 0 for v in a.values()),
        "differing_files": differing,
    }

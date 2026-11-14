"""Phase 1 consistency checks between design documents and configuration files."""

from __future__ import annotations

import re
import tomllib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

RULE_HEADING = re.compile(r"^### (BR-[A-Z]{3}-\d{3}) — (.+)$", re.MULTILINE)
RULE_ID = re.compile(r"^BR-[A-Z]{3}-\d{3}$")


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


@pytest.fixture(scope="module")
def rules(backend_dir: Path) -> dict[str, Any]:
    return load_toml(backend_dir / "config" / "business_rules.toml")


@pytest.fixture(scope="module")
def documented_rules(repo_root: Path) -> dict[str, str]:
    text = (repo_root / "docs" / "03-business-rules.md").read_text(encoding="utf-8")
    found = RULE_HEADING.findall(text)
    ids = [rule_id for rule_id, _ in found]
    assert len(ids) == len(set(ids)), "duplicate rule heading in 03-business-rules.md"
    return dict(found)


def test_every_documented_rule_has_a_config_entry_and_vice_versa(
    rules: dict[str, Any], documented_rules: dict[str, str]
) -> None:
    configured = set(rules["rules"])
    documented = set(documented_rules)
    assert documented - configured == set(), "rules documented but missing in TOML"
    assert configured - documented == set(), "rules in TOML but not documented"


def test_rule_titles_match_between_doc_and_config(
    rules: dict[str, Any], documented_rules: dict[str, str]
) -> None:
    for rule_id, doc_title in documented_rules.items():
        cfg_title = rules["rules"][rule_id]["title"]
        normalise = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
        assert normalise(cfg_title) == normalise(doc_title), rule_id


def test_rule_ids_are_well_formed(rules: dict[str, Any]) -> None:
    assert rules["meta"]["rules_version"]
    for rule_id, body in rules["rules"].items():
        assert RULE_ID.match(rule_id), rule_id
        assert isinstance(body.get("title"), str) and body["title"], rule_id


def test_key_rule_parameters(rules: dict[str, Any]) -> None:
    r = rules["rules"]
    assert r["BR-CAP-001"]["standard_weekly_hours"] == 40.0
    assert r["BR-SKL-002"]["freshness_days"] == 730
    bands = r["BR-UTL-002"]
    assert 0 < bands["under_utilized_below"] < bands["healthy_below"] <= 1
    sev = r["BR-GAP-006"]
    assert 1 > sev["low_min_coverage"] > sev["medium_min_coverage"] > sev["high_min_coverage"] > 0
    assert r["BR-REC-001"]["strategy_order"] == ["REALLOCATE", "TRAIN", "HIRE"]
    fct = r["BR-FCT-003"]
    assert fct["default_method"] in fct["available_methods"]


@pytest.mark.parametrize(
    ("mode", "employees", "skills", "projects", "weeks", "as_of"),
    [
        ("starter", 100, 30, 10, 13, date(2026, 3, 2)),
        ("full", 5000, 300, 500, 52, date(2026, 9, 28)),
    ],
)
def test_generator_configs_match_brief_and_calendar_decisions(
    backend_dir: Path,
    mode: str,
    employees: int,
    skills: int,
    projects: int,
    weeks: int,
    as_of: date,
) -> None:
    cfg = load_toml(backend_dir / "config" / f"generator.{mode}.toml")
    assert cfg["generator"]["mode"] == mode
    assert cfg["generator"]["seed"] == 20261022
    vol = cfg["volumes"]
    assert (vol["employees"], vol["skills"], vol["projects"]) == (employees, skills, projects)

    cal = cfg["calendar"]
    assert cal["horizon_weeks"] == weeks
    start = date.fromisocalendar(cal["planning_start_iso_year"], cal["planning_start_iso_week"], 1)
    assert start == date(2025, 12, 29)  # A-03: ISO 2026-W01 starts in calendar 2025
    derived_as_of = start + timedelta(weeks=weeks - cal["holdout_weeks"])
    assert derived_as_of == as_of  # A-02
    last_week = (start + timedelta(weeks=weeks - 1)).isocalendar()
    assert last_week.year == 2026 and last_week.week == weeks

    weights = cfg["supply"]["proficiency_weights"]
    assert len(weights) == 5 and abs(sum(weights) - 1.0) < 1e-9
    assert all(count > 0 for count in cfg["anomalies"].values())
    assert set(cfg["anomalies"]) == {
        "allocation_exceeds_availability",
        "expired_skill_treated_as_current",
        "duplicate_demand",
        "overlapping_allocation_conflict",
    }


def test_env_example_has_no_secret_values(repo_root: Path) -> None:
    values: dict[str, str] = {}
    for line in (repo_root / ".env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    assert values["WFIQ_DB_PASSWORD"] == ""
    assert all(k.startswith(("WFIQ_", "VITE_")) for k in values)

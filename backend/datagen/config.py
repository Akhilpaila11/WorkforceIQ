"""Generator configuration (backend/config/generator.<mode>.toml) and derived calendar."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cached_property
from typing import Any

from app.core.config import BACKEND_DIR
from app.domain.calendar import week_start
from app.domain.rules_config import RulesConfig, load_rules

CONFIG_DIR = BACKEND_DIR / "config"
MODES = ("starter", "full")


@dataclass(frozen=True)
class GeneratorConfig:
    mode: str
    seed: int
    generator_version: str
    planning_year: int
    horizon_start: date
    horizon_weeks: int
    holdout_weeks: int
    volumes: dict[str, int]
    supply: dict[str, Any]
    demand: dict[str, Any]
    actuals: dict[str, Any]
    anomalies: dict[str, int]
    config_sha256: str
    rules: RulesConfig

    @cached_property
    def as_of(self) -> date:
        """'Today' of the synthetic world = Monday of the first hold-out week (A-02)."""
        return self.horizon_start + timedelta(weeks=self.horizon_weeks - self.holdout_weeks)

    @cached_property
    def horizon_end(self) -> date:
        return self.horizon_start + timedelta(weeks=self.horizon_weeks, days=-1)

    @cached_property
    def weeks(self) -> tuple[date, ...]:
        return tuple(self.horizon_start + timedelta(weeks=i) for i in range(self.horizon_weeks))

    def rule(self, rule_id: str, name: str) -> Any:
        return self.rules.param(rule_id, name)


def load_config(mode: str, *, seed: int | None = None) -> GeneratorConfig:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    raw = (CONFIG_DIR / f"generator.{mode}.toml").read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    cal = data["calendar"]
    return GeneratorConfig(
        mode=data["generator"]["mode"],
        seed=int(seed if seed is not None else data["generator"]["seed"]),
        generator_version=data["generator"]["generator_version"],
        planning_year=cal["planning_start_iso_year"],
        horizon_start=week_start(cal["planning_start_iso_year"], cal["planning_start_iso_week"]),
        horizon_weeks=cal["horizon_weeks"],
        holdout_weeks=cal["holdout_weeks"],
        volumes=data["volumes"],
        supply=data["supply"],
        demand=data["demand"],
        actuals=data["actuals"],
        anomalies=data["anomalies"],
        config_sha256=hashlib.sha256(raw).hexdigest(),
        rules=load_rules(CONFIG_DIR / "business_rules.toml"),
    )

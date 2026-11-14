"""Typed access to ``backend/config/business_rules.toml``.

Every analysis run stores ``version`` and ``sha256`` so outputs remain traceable to the exact
parameters that produced them (BR-REC-005).
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.domain.errors import DomainValidationError

RULE_ID_PATTERN = re.compile(r"^BR-[A-Z]{3}-\d{3}$")


@dataclass(frozen=True, slots=True)
class RulesConfig:
    version: str
    sha256: str
    rules: Mapping[str, Mapping[str, Any]]

    @property
    def rule_ids(self) -> frozenset[str]:
        return frozenset(self.rules)

    def rule(self, rule_id: str) -> Mapping[str, Any]:
        try:
            return self.rules[rule_id]
        except KeyError:
            raise DomainValidationError(f"unknown business rule {rule_id}") from None

    def param(self, rule_id: str, name: str) -> Any:
        body = self.rule(rule_id)
        if name not in body:
            raise DomainValidationError(f"{rule_id} has no parameter {name!r}")
        return body[name]


def load_rules(path: Path) -> RulesConfig:
    raw = path.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    rules = data.get("rules", {})
    for rule_id, body in rules.items():
        if not RULE_ID_PATTERN.match(rule_id) or not isinstance(body.get("title"), str):
            raise DomainValidationError(f"malformed rule entry {rule_id!r} in {path.name}")
    frozen = {k: MappingProxyType(dict(v)) for k, v in rules.items()}
    return RulesConfig(
        version=str(data["meta"]["rules_version"]),
        sha256=hashlib.sha256(raw).hexdigest(),
        rules=MappingProxyType(frozen),
    )

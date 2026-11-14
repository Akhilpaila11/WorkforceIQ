"""Shared kernel - pure Python, imported by every module and by the data generator.

Rule: nothing in this package may import FastAPI or SQLAlchemy.

Phase 2 adds: ``enums`` (all allowed values), ``ids`` (ID formatting/parsing, BR-VAL-007),
``calendar`` (ISO weeks, working days, ISO-Thursday months - BR-CAP-002),
``units`` (hours <-> FTE, Decimal rounding - BR-CAP-001),
``rules_config`` (typed model of backend/config/business_rules.toml).
"""

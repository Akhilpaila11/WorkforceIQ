"""Static checks on the SQLAlchemy metadata (no database needed)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Enum, String

from app.db import data_dictionary
from app.db.registry import ALL_MODELS, MANDATORY_MODELS, metadata

MANDATORY = {
    "employee",
    "role",
    "skill",
    "employee_skill",
    "project",
    "demand_plan",
    "allocation",
    "availability",
    "training",
    "gap_analysis",
}
SUPPORTING = {
    "role_skill",
    "demand_skill_requirement",
    "demand_actual",
    "analysis_run",
    "capacity_snapshot",
    "forecast_result",
    "recommendation",
    "recommendation_gap_link",
    "exception_finding",
    "audit_event",
    "dataset_metadata",
    "id_sequence",
}
BRIDGES = {
    "role_skill": {"role_id", "skill_id"},
    "demand_skill_requirement": {"demand_id", "skill_id"},
    "recommendation_gap_link": {"recommendation_id", "gap_id"},
}
STRING_ID_TABLES = {
    "employee",
    "role",
    "skill",
    "employee_skill",
    "project",
    "allocation",
    "availability",
    "training",
    "gap_analysis",
    "analysis_run",
    "recommendation",
    "exception_finding",
}


def test_all_entities_present():
    names = {m.__tablename__ for m in MANDATORY_MODELS}
    assert names == MANDATORY
    assert set(metadata.tables) == MANDATORY | SUPPORTING
    assert len(ALL_MODELS) == len(metadata.tables) == 22


def test_every_table_has_pk_comment_and_described_columns():
    for table in metadata.tables.values():
        assert table.primary_key.columns, table.name
        assert table.comment, table.name
        for col in table.columns:
            assert col.comment, f"{table.name}.{col.name} has no description"


def test_bridge_tables_have_composite_pk_of_two_foreign_keys():
    for name, cols in BRIDGES.items():
        table = metadata.tables[name]
        assert {c.name for c in table.primary_key.columns} == cols
        assert all(table.columns[c].foreign_keys for c in cols)


def test_foreign_keys_restrict_delete():
    for table in metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.ondelete == "RESTRICT", f"{table.name}.{fk.parent.name}"


def test_enum_columns_are_varchar_with_check():
    seen = 0
    for table in metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, Enum):
                seen += 1
                assert col.type.native_enum is False
                assert col.type.create_constraint is True
    assert seen >= 30


def test_string_ids_have_format_checks():
    for name in STRING_ID_TABLES:
        table = metadata.tables[name]
        pk = next(iter(table.primary_key.columns))
        assert isinstance(pk.type, String)
        names = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
        assert f"ck_{name}_{pk.name}_format" in names, name


def test_hours_columns_declare_units():
    for table in metadata.tables.values():
        for col in table.columns:
            if col.name.endswith("_hours") or col.name in {"hours", "hours_per_week"}:
                assert col.info.get("units") == "hours", f"{table.name}.{col.name}"


def test_data_dictionary_is_up_to_date():
    assert data_dictionary.main(["--check"]) == 0

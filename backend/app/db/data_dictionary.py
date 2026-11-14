"""Generate ``docs/07-data-dictionary.md`` from the SQLAlchemy models.

The dictionary is *derived* from the code, so it cannot drift from the schema:
a unit test runs ``--check`` and fails if the committed file is out of date.

Usage (PowerShell, from ``backend/``)::

    .\\.venv\\Scripts\\python.exe -m app.db.data_dictionary          # rewrite the file
    .\\.venv\\Scripts\\python.exe -m app.db.data_dictionary --check  # verify only
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sqlalchemy import Boolean, CheckConstraint, Column, Enum, Index, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.dialects.sqlite.base import SQLiteDialect
from sqlalchemy.engine import Dialect
from sqlalchemy.sql.elements import ClauseElement, TextClause

from app.core.config import REPO_ROOT
from app.db.registry import ALL_MODELS, MANDATORY_MODELS, metadata

OUTPUT = REPO_ROOT / "docs" / "07-data-dictionary.md"
_PG: Dialect = PGDialect()  # type: ignore[no-untyped-call]  # SQLAlchemy leaves __init__ untyped
_SQLITE: Dialect = SQLiteDialect()
NONE = "—"


def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _type(col: Column[object], dialect: Dialect) -> str:
    return str(col.type.compile(dialect=dialect))


def _default(col: Column[object]) -> str:
    if col.identity is not None:
        return "identity (auto-increment)"
    if col.server_default is not None:
        arg = getattr(col.server_default, "arg", None)
        if isinstance(arg, TextClause):
            return f"DB: `{arg.text}`"
        if isinstance(arg, ClauseElement):
            return f"DB: `{arg.compile(dialect=_PG)}`"
        return f"DB: `{arg}`"
    if col.default is not None:
        arg = getattr(col.default, "arg", None)
        if callable(arg):
            return "app: current UTC time"
        return f"app: `{arg}`"
    return NONE


def _allowed(col: Column[object]) -> str:
    if isinstance(col.type, Enum):
        return ", ".join(col.type.enums)
    if isinstance(col.type, Boolean):
        return "true, false"
    return NONE


def _key(col: Column[object]) -> str:
    parts = ["PK"] if col.primary_key else []
    parts += [f"FK → {fk.target_fullname}" for fk in sorted(col.foreign_keys, key=str)]
    return "; ".join(parts) or NONE


def _unique(col: Column[object], table: Table) -> str:
    if col.unique:
        return "Yes"
    notes = []
    for cons in table.constraints:
        if isinstance(cons, UniqueConstraint) and col.name in cons.columns:
            notes.append("Yes" if len(cons.columns) == 1 else f"with {cons.name}")
    for idx in sorted(table.indexes, key=lambda i: str(i.name)):
        if idx.unique and col.name in idx.columns:
            partial = " (partial)" if _where(idx) else ""
            notes.append(("Yes" if len(idx.columns) == 1 else f"in `{idx.name}`") + partial)
    if col.primary_key and len(table.primary_key.columns) == 1:
        notes.insert(0, "Yes (PK)")
    return "; ".join(notes) or "No"


def _where(idx: Index) -> str | None:
    clause = idx.dialect_options["postgresql"].get("where")
    return None if clause is None else str(clause)


def _checks(table: Table) -> list[CheckConstraint]:
    return sorted(
        (
            c
            for c in table.constraints
            if isinstance(c, CheckConstraint) and not getattr(c, "_type_bound", False)
        ),
        key=lambda c: str(c.name),
    )


def _validation(col: Column[object], table: Table) -> str:
    rules = [
        f"`{c.name}`"
        for c in _checks(table)
        if re.search(rf"\b{re.escape(col.name)}\b", str(c.sqltext))
    ]
    if isinstance(col.type, Enum):
        rules.insert(0, "value in allowed list (CHECK)")
    return ", ".join(rules) or NONE


def _column_row(col: Column[object], table: Table) -> str:
    cells = [
        f"`{col.name}`",
        _type(col, _PG),
        _type(col, _SQLITE),
        "No" if col.nullable else "Yes",
        _default(col),
        _allowed(col),
        _key(col),
        _unique(col, table),
        str(col.info.get("units", NONE)),
        _validation(col, table),
        col.comment or NONE,
    ]
    return "| " + " | ".join(_md(c) for c in cells) + " |"


def render() -> str:
    entity_of = {m.__table__.name: m.__name__ for m in ALL_MODELS}  # type: ignore[attr-defined]
    mandatory = {m.__table__.name for m in MANDATORY_MODELS}  # type: ignore[attr-defined]
    tables = sorted(
        metadata.tables.values(), key=lambda t: (t.name not in mandatory, entity_of[t.name])
    )
    out: list[str] = [
        "# 07 — Data Dictionary",
        "",
        "> **Generated** from the SQLAlchemy models by `python -m app.db.data_dictionary`."
        " Do not edit by hand — a unit test fails if this file is out of date.",
        "",
        "Conventions: *Req* = NOT NULL. *Type (PostgreSQL)* is the target type; *SQLite* is the"
        " storage type used in development (decision A-35). Hours are stored with 2 decimals and"
        " handled as exact `Decimal` values in Python. Named CHECK constraints are listed per"
        " table; the *Validation* column names the constraints that involve the field."
        " Foreign keys use `ON DELETE RESTRICT`. Rules that span rows or need the calendar"
        " (e.g. one PRIMARY skill per demand line, week_start_date is a Monday) are enforced in"
        " the domain/service layer and the BR-VAL checks.",
        "",
        "## Entities",
        "",
        "| # | Entity | Table | Kind | Columns | Description |",
        "|---|---|---|---|---|---|",
    ]
    for n, table in enumerate(tables, 1):
        kind = "Mandatory" if table.name in mandatory else "Supporting"
        out.append(
            f"| {n} | {entity_of[table.name]} | `{table.name}` | {kind} | {len(table.columns)}"
            f" | {_md(table.comment or NONE)} |"
        )
    for n, table in enumerate(tables, 1):
        pk = ", ".join(f"`{c.name}`" for c in table.primary_key.columns)
        out += [
            "",
            f"## {n}. {entity_of[table.name]} (`{table.name}`)",
            "",
            _md(table.comment or NONE),
            "",
            f"**Primary key:** {pk}",
            "",
            "| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key"
            " | Unique | Units | Validation | Description |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        out += [_column_row(col, table) for col in table.columns]
        checks = _checks(table)
        if checks:
            out += ["", "**CHECK constraints**", ""]
            out += [f"- `{c.name}`: `{_md(str(c.sqltext))}`" for c in checks]
        if table.indexes:
            out += ["", "**Indexes**", ""]
            for idx in sorted(table.indexes, key=lambda i: str(i.name)):
                cols = ", ".join(c.name for c in idx.columns)
                where = _where(idx)
                suffix = f" WHERE `{_md(where)}`" if where else ""
                unique = "UNIQUE " if idx.unique else ""
                out.append(f"- `{idx.name}`: {unique}({cols}){suffix}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the file is outdated")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    content = render()
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current != content:
            print(f"{args.output} is out of date; run python -m app.db.data_dictionary")
            return 1
        print(f"{args.output} is up to date")
        return 0
    args.output.write_bytes(content.encode("utf-8"))
    print(f"wrote {args.output} ({content.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Database migrations (Alembic)

Each schema change is a versioned script in `versions/`, so the database can be rebuilt from
scratch or upgraded step by step. The connection URL is **never** stored in `alembic.ini`;
`env.py` reads it from the `WFIQ_*` settings (`.env`).

| Revision | Content |
|---|---|
| `0001_initial_schema` | 22 tables, all keys/CHECKs/indexes, plus hand-written guards: append-only `audit_event`, non-overlapping work schedules (SQLite triggers / PostgreSQL trigger + `EXCLUDE USING gist`) |

## Commands (PowerShell, from `backend/`)

```powershell
.\.venv\Scripts\alembic.exe current              # which revision the database is at
.\.venv\Scripts\alembic.exe upgrade head         # apply all migrations (creates the SQLite file)
.\.venv\Scripts\alembic.exe check                # fail if the models differ from the database
.\.venv\Scripts\alembic.exe history              # list revisions
.\.venv\Scripts\alembic.exe downgrade -1         # undo the latest migration (DESTROYS its tables)
.\.venv\Scripts\alembic.exe upgrade head --sql   # print the SQL instead of running it

# Target a different database explicitly (e.g. a disposable one):
.\.venv\Scripts\alembic.exe -x url=sqlite+pysqlite:///C:/temp/scratch.sqlite3 upgrade head
.\.venv\Scripts\alembic.exe -x url=postgresql+psycopg://user@localhost/db upgrade head --sql
```

## Creating a new migration

1. Change the SQLAlchemy models.
2. `.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe change"`
3. **Review the generated file** (autogenerate does not see triggers, CHECK changes or
   dialect-specific DDL), then `upgrade head`, run `pytest`, and regenerate the data dictionary:
   `.\.venv\Scripts\python.exe -m app.db.data_dictionary`.

Safety: tests only migrate temporary SQLite copies. `downgrade` is never run by tests against
your development database, and no command here drops a database.

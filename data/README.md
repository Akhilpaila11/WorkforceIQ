# Data

## `db/` — local databases (git-ignored)

`workforceiq.sqlite3` is the development database (decision A-35). Create or upgrade it with
`.\.venv\Scripts\alembic.exe upgrade head` from `backend/`. Tests never use this file; they
work on temporary copies.

## `generated/` — synthetic datasets (Phase 3, git-ignored)

```
generated/<starter|full>/
  csv/            input tables (one CSV per table, sorted by primary key)
  json/           the same tables as JSON
  sql/seed.sql    seed script
  ground_truth/   labelled anomalies — kept apart from the input data,
                  never loaded into the application database
  manifest.json   row counts and SHA-256 checksums
```

Both folders can be re-created exactly (schema from migrations; data from the seed and
configuration). All data is fully synthetic; no external data sources are used.

# Progress Checklist

Legend: `[x]` done and verified · `[ ]` not started · `[~]` in progress

## Phase 1 — Requirements, rules, architecture, ER diagram, structure
- [x] Inspect workspace and development environment
- [x] Requirements ([01](01-requirements.md))
- [x] Assumptions and decisions log ([02](02-assumptions-and-decisions.md))
- [x] Business rule catalogue + parameter file ([03](03-business-rules.md), `backend/config/business_rules.toml`)
- [x] Architecture, SOLID mapping, API surface ([04](04-architecture.md))
- [x] ER diagram, entity specifications, ID conventions, lifecycles ([05](05-data-model.md))
- [x] Synthetic data / ground truth / evaluation design ([06](06-synthetic-data-and-evaluation.md))
- [x] Folder structure, configuration files, `.env.example`, README
- [x] Python virtual environment + dependency install + lock file
- [x] Phase 1 verification tests (settings, config/doc consistency, structure)

## Phase 2 — Database
- [x] Project moved to `C:\CandidateWorkspace\WorkforceIQ` (git root), venv recreated, checks re-run
- [x] Database engine: SQLite for development (user decision; A-35), schema PostgreSQL-compatible
- [x] `.env` created; connectivity verified (`python -m app.core.database`, foreign keys ON)
- [x] Shared kernel: enums, IDs, ISO-week calendar, units, lifecycles, errors, rules loader
- [x] SQLAlchemy models: 10 mandatory + 12 supporting tables (22; `id_sequence` added, A-38)
- [x] Constraints: PK, FK (RESTRICT), UNIQUE, CHECK (enums, dates, ranges, identities), partial unique indexes
- [x] Immutable identifiers (ORM guard), append-only audit trail (DB triggers), schedule-overlap guard
- [x] Repository Protocols + SQLAlchemy implementations, audit recorder, ID allocator, `EmployeeSkillService`
- [x] Alembic configured; `0001_initial_schema` upgrade → check → downgrade → upgrade on SQLite
- [x] Dev database migrated to `0001 (head)`
- [x] PostgreSQL DDL rendered offline and asserted in tests
- [x] Data dictionary generated from the models ([07](07-data-dictionary.md)) with an up-to-date test
- [ ] **Blocked:** migration run on a live PostgreSQL server (no server; test skips until `WFIQ_TEST_PG_URL` is set)

## Phase 3 — Synthetic data
- [x] Generator (`python -m datagen`, starter + full; NumPy + Faker, seed 20261022, per-stage streams)
- [x] Roles/role-skill taxonomy, employees, part-time schedules, leave, versioned skills, training
- [x] Projects, weekly demand lines (role + skill), allocations, synthetic actuals (from the clean plan)
- [x] Clean baseline verified anomaly-free, then 4 labelled anomaly types injected
- [x] Ground truth in separate files; no label leakage (IDs renumbered after injection, no tell-tale text)
- [x] CSV / JSON / SQL seed / derived exports + source manifest + validation summary
- [x] Validation: 20 checks (BR-VAL-001..009, anomalies present == ground truth) — starter and full
- [x] Reproducibility: two runs identical (row counts + SHA-256) — starter and full
- [x] Loader into SQLite (safe, repeatable, one transaction); seed.sql loads into a fresh database
- [x] Tests: 11 generator tests; full suite 157 passed, 1 skipped (live PostgreSQL, blocked)

## Phase 4 — API
- [x] App factory (`app.main:create_app`), Swagger `/docs`, OpenAPI `/openapi.json`, CORS for Vite
- [x] Core: JSON logging with request IDs, central error handling (one error shape; 404/405/422/503/500), session per request, pagination
- [x] Repositories (Protocols + SQLAlchemy) with filters; generic read services; composition root `api/deps.py`
- [x] Read endpoints under `/api/v1`: health, employees (+ skills), roles, skills, projects (+ demand), allocations, availability, training, dashboard summary
- [x] Tests: 49 API tests (starter dataset in an isolated DB + empty DB + unmigrated DB); full suite 206 passed, 1 skipped (live PostgreSQL, blocked)
- [x] Verified with a live uvicorn server against the Phase 3 starter database
- [ ] Write endpoints (POST/PATCH) and audit events — not requested in Phase 4; added when a use-case needs them

## Phase 5 — Analytics
- [x] Capacity & utilization: gross/leave/training/net/allocated/free per employee-week, part-time, FTE, risk bands, bench (BR-CAP-*, BR-UTL-001..005)
- [x] Forecasting: NAIVE_PLAN, MOVING_AVERAGE, PLAN_RATIO (default) with no look-ahead; MAE/WAPE/BIAS on hold-out weeks with actuals; roll-ups by project/role/skill/week/month
- [x] Skill status + eligibility + match score (BR-SKL-002/006/007); coverage, at-risk hours and gaps (BR-GAP-001..007, PLANNED or FORECAST basis)
- [x] Recommendations REALLOCATE → TRAIN → HIRE over one capacity ledger (no double counting); rule IDs, explanation, assumptions, source refs, gap links
- [x] Anomaly detection, 4 rules (+ informational stale skills); evaluation vs the separate ground truth only after detection: precision/recall/F1 = 1.0 on starter and full
- [x] Persistence per run (analysis_run, capacity_snapshot, forecast_result, gap_analysis, recommendation(+links), exception_finding, audit events); FAILED runs keep no partial results; deterministic re-runs
- [x] API: `POST/GET /analysis/runs`, forecasts, capacity, gap analysis, exceptions, recommendations, dashboard metrics
- [x] Tests: 37 engine unit tests + 22 analysis API tests; full suite 265 passed, 1 skipped (live PostgreSQL, blocked)
- [x] Verified on the dev starter database and on the full dataset loaded from its existing `seed.sql` (no regeneration; run ≈ 70 s)

## Phase 6 — Frontend
- [x] Vite + React 18 + TypeScript dashboard (plain CSS, SVG chart; no extra UI libraries)
- [x] Six tabs wired to the API: overview, forecasting, skill gaps, utilization, anomalies, recommendations; loading/empty/error states; run-analysis action
- [x] Verified with backend + Vite dev server on the starter database; `npm run build` passes

## Phase 7 — Submission
- [ ] Full test run, reports (validation, reproducibility, accuracy)
- [ ] Data dictionary, source manifest, API docs, demo script
- [ ] Final README

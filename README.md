# WorkforceIQ

**Intelligent Workforce Demand Forecasting and Skill Gap Analysis System**

WorkforceIQ forecasts how many hours of work each project needs — by role, skill and week — and
compares that demand with the real capacity of the workforce (after part-time schedules, leave,
training and existing allocations). It finds skill gaps and excess capacity, flags data problems
(over-allocation, expired skills, duplicate demand, conflicting assignments), recommends whether
to **reallocate, train or hire**, and explains every recommendation with rule IDs and source
records.

> **Status:** working end to end — backend, analysis engines and React dashboard. See
> [docs/PROGRESS.md](docs/PROGRESS.md).

## Quick start (demo)

Two PowerShell terminals, after the one-time setup below (steps 1–4):

```powershell
# Terminal 1 - backend API on http://localhost:8000 (Swagger: /docs)
cd C:\CandidateWorkspace\WorkforceIQ\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --port 8000

# Terminal 2 - dashboard on http://localhost:5173
cd C:\CandidateWorkspace\WorkforceIQ\frontend
npm install        # first time only
npm run dev
```

Open http://localhost:5173. If no analysis run exists yet, click **Run analysis**; the tabs
then show Overview KPIs, Forecasting (project/role filters), Skill gaps, Utilization, Anomalies
(all four types with severity, records and explanations) and Recommendations
(reallocate / train / hire with reasons). Every number comes from the API.

**Project root:** `C:\CandidateWorkspace\WorkforceIQ` — open this folder in VS Code
(*File → Open Folder…*); all commands below assume it.

---

## Architecture at a glance

| Tier | Technology | Folder |
|---|---|---|
| 1 · Presentation | React 18, TypeScript, Vite (plain CSS, SVG chart) | `frontend/` |
| 2 · Business logic | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 (modular monolith) | `backend/app/` |
| 3 · Data | **SQLite** in development; schema and migrations **PostgreSQL 17-compatible** (A-35) | `backend/migrations/` |
| Offline tool | Deterministic synthetic data generator (seed 20261022, NumPy + Faker) | `backend/datagen/` |

Details, diagrams and the SOLID mapping: [docs/04-architecture.md](docs/04-architecture.md).

## Documentation

| Document | Contents |
|---|---|
| [01 Requirements](docs/01-requirements.md) | Problem, users, functional and non-functional requirements, scope |
| [02 Assumptions & decisions](docs/02-assumptions-and-decisions.md) | Every ambiguity and how it was resolved; Phase 2 decisions and design corrections |
| [03 Business rules](docs/03-business-rules.md) | 68 rules `BR-*` with formulas (parameters in `backend/config/business_rules.toml`) |
| [04 Architecture](docs/04-architecture.md) | Tiers, modules, layering, SOLID, request flow, API surface, testing strategy |
| [05 Data model](docs/05-data-model.md) | ER diagram, entity specifications, ID conventions, lifecycles, history, indexes |
| [06 Synthetic data & evaluation](docs/06-synthetic-data-and-evaluation.md) | Generator design, anomaly injection, ground truth, metrics, reproducibility |
| [07 Data dictionary](docs/07-data-dictionary.md) | Every field of all 22 tables — **generated from the models** |
| [Migrations](backend/migrations/README.md) | Alembic commands |
| [Progress](docs/PROGRESS.md) | Phase checklist |

## Project structure

```
WorkforceIQ/                       ← Git repository root
├── README.md
├── .env.example                   every environment variable (copy to .env)
├── .gitignore / .gitattributes / .editorconfig
├── .vscode/settings.json          interpreter = backend\.venv, pytest from backend/
├── docs/                          design documents 01–07 + progress checklist
├── backend/
│   ├── pyproject.toml             dependencies + pytest / ruff / mypy settings
│   ├── requirements-lock.txt      exact versions installed and tested
│   ├── alembic.ini                Alembic settings (no credentials)
│   ├── config/                    business_rules.toml, generator.starter.toml, generator.full.toml
│   ├── app/
│   │   ├── main.py                FastAPI app factory (create_app)
│   │   ├── core/                  settings, database, errors, logging, params (pagination, IDs)
│   │   ├── domain/                enums, ids, calendar, units, lifecycles, errors, rules_config
│   │   ├── db/                    base, types, constraints, guards, repository, audit, ids,
│   │   │                          platform models, registry, data_dictionary generator
│   │   ├── modules/               queries.py: generic read services
│   │   │   ├── workforce/         models, schemas, repositories, sql_repositories, services, router
│   │   │   ├── projects/          models, schemas, sql_repositories, router
│   │   │   ├── analytics/         engines (capacity, skills, demand, forecasting, gaps,
│   │   │   │                      recommendations, detection, evaluation), pipeline, API
│   │   │   └── reporting/         dashboard summary: schemas, services, sql_repositories, router
│   │   └── api/                   deps.py (composition root), v1/router.py (health + routers)
│   ├── migrations/                env.py, script.py.mako, versions/0001_initial_schema.py
│   ├── datagen/                   generator: master, workload, anomalies, capacity, checks,
│   │                              export, loader, pipeline (python -m datagen)
│   └── tests/                     unit/, integration/, factories.py, conftest.py
├── frontend/                      React + Vite dashboard: src/App.tsx (tabs), src/api.ts (typed client)
├── data/
│   ├── db/                        SQLite database files (git-ignored)
│   └── generated/<mode>/          generator output (git-ignored, reproducible)
└── scripts/check-prereqs.ps1      checks Python, Node, git (PostgreSQL optional)
```

## Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | 3.13 (3.12+ supported) | `py -3.13 --version` |
| Node.js + npm | 20+ | `node --version` |
| Git | any recent | `git --version` |
| PostgreSQL | 17 — **optional** (SQLite is the default) | `psql --version` |

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check-prereqs.ps1
```

## Setup (Windows PowerShell)

### 1. Python environment

```powershell
cd C:\CandidateWorkspace\WorkforceIQ\backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt   # exact tested versions
.\.venv\Scripts\python.exe -m pip install -e . --no-deps             # the project itself
```

(Optional) activate it: `.\.venv\Scripts\Activate.ps1` — if blocked, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

### 2. Configuration

```powershell
cd C:\CandidateWorkspace\WorkforceIQ
Copy-Item .env.example .env      # SQLite needs no password; .env is git-ignored
```

### 3. Database (SQLite, default)

```powershell
cd C:\CandidateWorkspace\WorkforceIQ\backend
.\.venv\Scripts\python.exe -m app.core.database   # connectivity check (creates data\db\ on first use)
.\.venv\Scripts\alembic.exe upgrade head           # create / upgrade all 22 tables
.\.venv\Scripts\alembic.exe current                # should print: 0001 (head)
```

More commands: [backend/migrations/README.md](backend/migrations/README.md).

### 3b. Optional: PostgreSQL 17 instead of SQLite

Installation needs administrator rights; you type the `postgres` password in the installer
yourself, so it is never stored anywhere:

```powershell
winget install --id PostgreSQL.PostgreSQL.17 --interactive
# add C:\Program Files\PostgreSQL\17\bin to PATH, open a new terminal, then:
psql -U postgres -h localhost -c "CREATE ROLE workforceiq_app LOGIN;"
psql -U postgres -h localhost -c "\password workforceiq_app"
psql -U postgres -h localhost -c "CREATE DATABASE workforceiq OWNER workforceiq_app;"
psql -U postgres -h localhost -c "CREATE DATABASE workforceiq_test OWNER workforceiq_app;"
```

Then set `WFIQ_DB_BACKEND=postgresql` and `WFIQ_DB_PASSWORD=...` in `.env` and run step 3 again.
To run the live PostgreSQL migration test against the **disposable** test database:
`$env:WFIQ_TEST_PG_URL = "postgresql+psycopg://workforceiq_app:<password>@localhost/workforceiq_test"`.

### 4. Synthetic data

```powershell
cd C:\CandidateWorkspace\WorkforceIQ\backend
.\.venv\Scripts\python.exe -m datagen --mode starter                          # ~2 s, loads SQLite
.\.venv\Scripts\python.exe -m datagen --mode full --check-reproducibility     # ~2 min
```

| Mode | Employees | Skills | Projects | Weeks | Anomaly events (over-alloc / expired / duplicate / conflict) |
|---|---|---|---|---|---|
| starter | 100 | 30 | 10 | 13 | 6 / 8 / 5 / 5 |
| full | 5,000 | 300 | 500 | 52 | 120 / 200 / 60 / 80 |

Options: `--no-load` (files only), `--db-url <url>` (other database), `--seed <n>`,
`--check-reproducibility` (generates twice; compares row counts and SHA-256 of every file).
Loading replaces only the dataset and analysis tables (never `audit_event`, never the file).

Output in `data/generated/<mode>/`: `csv/`, `json/`, `sql/seed.sql` (input tables),
`ground_truth/` (labels — kept apart, never loaded into the database), `derived/` (weekly
capacity, role demand/supply balance, skill eligibility), `manifest.json` (source manifest:
provenance, row counts, SHA-256), `validation_summary.json`, `reproducibility.json`.

### 5. Run the API

```powershell
cd C:\CandidateWorkspace\WorkforceIQ\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload --port 8000
```

Swagger UI: http://localhost:8000/docs · OpenAPI: http://localhost:8000/openapi.json ·
health: http://localhost:8000/api/v1/health. The API reads the database configured in `.env`
(load data first with step 4). CORS allows `WFIQ_CORS_ORIGINS` (Vite: `http://localhost:5173`).

| Endpoint (under `/api/v1`) | Filters (all optional) |
|---|---|
| `GET /health` | — |
| `GET /employees`, `GET /employees/{id}` | `role_id`, `status`, `seniority`, `location`, `skill_id` (current holders), `search` |
| `GET /employees/{id}/skills` | `skill_id`, `recorded_status`, `min_proficiency`, `include_history` |
| `GET /roles`, `GET /skills` | `role_family`, `is_active`; `category`, `requires_certification`, `search` |
| `GET /projects`, `GET /projects/{id}` | `status`, `priority`, `business_unit`, `search`, `date_from`/`date_to` |
| `GET /projects/{id}/demand` | `role_id`, `skill_id`, `status`, `source`, `date_from`/`date_to` (week start) |
| `GET /allocations` | `employee_id`, `project_id`, `role_id`, `allocation_type`, `status`, `date_from`/`date_to` |
| `GET /availability` | `employee_id`, `availability_type`, `status`, `date_from`/`date_to` |
| `GET /training` | `employee_id`, `skill_id`, `training_type`, `status`, `date_from`/`date_to` |
| `GET /dashboard/summary` | — (totals from the stored records) |

Lists return `{items, page, page_size, total, pages}` (`?page=1&page_size=50`, max 200);
date windows keep records that overlap them. Errors always have the shape
`{"error": {"code", "message", "details", "request_id"}}`: 404 unknown record, 422 invalid or
unknown parameter / malformed ID, 409 run without results, 503 database unavailable.

### 6. Run the analysis

With the API running (step 5), start a full analysis run: capacity, forecasts, skill gaps,
recommendations, anomaly detection and its evaluation against the separate ground truth. Every
result is stored under a new run ID, together with the rules version and hash.

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/analysis/runs        # defaults
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/analysis/runs `
  -ContentType application/json -Body '{"demand_basis": "FORECAST"}'              # options
```

Optional body fields: `as_of_date` (default: the dataset's), `demand_basis` (`PLANNED` |
`FORECAST`), `forecast_method` (`PLAN_RATIO` | `MOVING_AVERAGE` | `NAIVE_PLAN`). The starter
dataset takes under 1 s and the full dataset about 70 s (synchronous request).

| Endpoint (under `/api/v1`) | Returns |
|---|---|
| `POST /analysis/runs`, `GET /analysis/runs[/{id}]` | Run status, parameters, headline summary, assumptions |
| `GET /forecasts/results`, `/forecasts/summary`, `/forecasts/evaluation` | Forecast per project/role/week; roll-ups by project, role, skill, week/month; MAE/WAPE/BIAS |
| `GET /capacity/summary` | Gross, leave, training, net, allocated, available hours, utilization, FTE (by week, month or role) |
| `GET /gap-analysis`, `/gap-analysis/summary` | Coverage and gaps per project/role/skill/week; aggregates |
| `GET /exceptions`, `/exceptions/evaluation` | The four anomaly types (+ informational stale skills); precision/recall/F1 |
| `GET /recommendations[/{id}]` | REALLOCATE / TRAIN / HIRE with rule IDs, explanation, assumptions, linked gaps |
| `GET /dashboard/metrics` | Headline metrics, top gaps and a weekly demand/capacity series |

Result endpoints take an optional `run_id` (default: the latest successful run).

### 7. Frontend

```powershell
cd C:\CandidateWorkspace\WorkforceIQ\frontend
npm install
npm run dev        # http://localhost:5173 (calls VITE_API_BASE_URL, else proxies /api to :8000)
npm run build      # type-check + production build into frontend/dist
```

### 8. Verify

```powershell
cd C:\CandidateWorkspace\WorkforceIQ\backend
.\.venv\Scripts\python.exe -m pytest                      # unit + integration tests
.\.venv\Scripts\python.exe -m ruff check .                # lint
.\.venv\Scripts\python.exe -m ruff format --check .       # formatting
.\.venv\Scripts\python.exe -m mypy                        # static types (strict)
.\.venv\Scripts\python.exe -m app.db.data_dictionary --check   # dictionary matches models
```

## Key conventions

- **Hours** are the canonical capacity unit; **1 FTE = 40 h/week**.
- Planning periods are **ISO weeks**; 2026-W01 starts on Monday 2025-12-29.
- IDs are deterministic and immutable: `EMP-000001`, `SKL-000001`, `PRJ-2026-000001`,
  `DEM-PRJ-2026-000001-2026W01-01`, `ALLOC-2026-000001`.
- Business rules have IDs (`BR-CAP-001` …); every recommendation stores the rules that produced it.
- Credentials only ever come from environment variables; `.env` is git-ignored.
- Data is **fully synthetic**; ground-truth labels are kept in separate files and never loaded into
  the application database.

## Roadmap

1. ✅ Requirements, business rules, architecture, ER diagram, folder structure
2. ✅ Database schema, SQLAlchemy models, Alembic migrations, data dictionary
3. ✅ Synthetic data generator, fixed-seed reproducibility, validation
4. ✅ FastAPI services, repositories and REST endpoints
5. ✅ Forecasting, capacity, skill gaps, anomaly detection, recommendations
6. ✅ React frontend and API integration
7. Testing, reports, documentation and submission

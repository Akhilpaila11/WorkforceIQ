# 02 — Assumptions and Design Decisions

The brief leaves a number of business questions open. Each one is resolved below with a
decision and its reason. Decisions are referenced from other documents as `A-xx`.
Rule IDs (`BR-…`) point to [03-business-rules.md](03-business-rules.md).

## Time and calendar

| ID | Ambiguity | Decision | Why |
|---|---|---|---|
| A-01 | What is a "planning period"? | The **ISO-8601 week** (Monday–Sunday). Monthly views roll weeks up to the month containing the week's **Thursday** (BR-CAP-002). | The mandated demand ID `DEM-…-2026W01` is weekly; the ISO-Thursday rule gives every week exactly one month. |
| A-02 | Which dates does the synthetic world cover, and what is "today"? | Horizon starts at **2026-W01 (Mon 2025-12-29)**. Starter = 13 weeks (W01–W13). Full = 52 weeks (W01–W52; 2026 has 53 ISO weeks, W53 is excluded). **`as_of_date`** ("today" in the synthetic world) = Monday of the first forecast hold-out week: **2026-03-02** (starter) / **2026-09-28** (full). | One fixed reference date makes every derived status reproducible. The generator never reads the system clock. |
| A-03 | Note on ISO years | Week `2026W01` begins in calendar year 2025. Demand IDs use the **ISO year**, not the calendar year. | Avoids a classic off-by-one bug around New Year. |
| A-04 | Public holidays? | **Not modelled.** A holiday can be entered as leave. | Keeps capacity maths simple and country-neutral. |

## Capacity

| ID | Ambiguity | Decision | Why |
|---|---|---|---|
| A-05 | Capacity unit and FTE | **Hours** are canonical. **1 FTE = 40 h/week** (BR-CAP-001). Working days Mon–Fri; daily hours = weekly hours / 5 (part-timers are spread evenly). | One unit avoids rounding drift; FTE is just a display conversion. |
| A-06 | Where do part-time hours live, and how do they change over time? | As **effective-dated `WORK_SCHEDULE` rows in `availability`** (one schedule active per employed day, BR-VAL-009). FULL_TIME/PART_TIME is **derived** (`weekly_hours < 40` ⇒ part-time), not stored separately. | Single source of truth; a change from 40 h to 24 h is a new row, so history is preserved. |
| A-07 | Does leave reduce allocations? | **No.** Leave reduces *capacity*; allocations keep their booked hours (BR-CAP-008). | This is exactly how real over-allocation arises (leave approved after staffing) and is what the detector must catch. |
| A-08 | Does training consume capacity? | **Yes**, `hours_per_week` of PLANNED/IN_PROGRESS training is deducted (BR-CAP-006). | Training recommendations must not assume time the employee does not have. |
| A-09 | Which statuses count? | Leave: APPROVED. Allocations: CONFIRMED and COMPLETED (PROPOSED is shown as "soft-booked" only). Demand: SUBMITTED and APPROVED lines on APPROVED/ACTIVE projects. All configurable. | Avoids planning on tentative data while still displaying it. |

## Skills

| ID | Ambiguity | Decision | Why |
|---|---|---|---|
| A-10 | "Expired" vs "stale" | **EXPIRED**: `expiry_date < date` (hard, certifications). **STALE**: last verification older than **730 days** (soft). **PENDING**: not yet verified. Only **VALID** skills make an employee eligible (BR-SKL-002, BR-SKL-006). | Distinguishes a lapsed certificate from an assessment that is merely old. |
| A-11 | What does "expired skill incorrectly treated as current" mean in data? | Each `employee_skill` row has a **`recorded_status`** copied from the source HR system. The system **derives** the real status from dates and never trusts the recorded flag. The anomaly = recorded `CURRENT` but derived `EXPIRED` at `as_of_date` (BR-SKL-004). | Models a realistic data-quality defect and proves eligibility logic is date-driven. |
| A-12 | On which date is eligibility checked for a week? | The week's **Monday** (`evaluate_on = WEEK_START`). | Deterministic and simple; a skill expiring mid-week counts as valid for that week. |
| A-13 | Must the employee's role match the demand role exactly? | No: **same role family** is required; an exact role match increases the match score (BR-SKL-007). | Realistic flexibility (e.g. Backend ↔ Full-stack engineer) without matching a designer to a DBA job. |
| A-14 | How many skills can a demand line require? | Exactly **one PRIMARY** (mandatory, with a minimum proficiency) and **0–2 SECONDARY** (preferred, only affect ranking). Gap hours are attributed to the primary skill. | Makes gap attribution unambiguous ("which skill is short?"). |

## Demand, allocation and anomalies

| ID | Ambiguity | Decision | Why |
|---|---|---|---|
| A-15 | What is a duplicate demand line? | Two lines of the same project, week, role, primary skill and minimum proficiency (BR-DEM-004). The baseline generator guarantees this key is unique, so any repeat is a duplicate. The **lowest line number is kept**; later lines are flagged and excluded from analysis totals. | Prevents inflated demand from triggering unnecessary hires. |
| A-16 | Overlapping allocation conflict vs over-allocation | Different problems: **over-allocation** = too many hours (BR-UTL-004). **Conflict** = an employee has any other allocation overlapping a **DEDICATED** (exclusive, ring-fenced) allocation, even if hours fit (BR-ALC-003). Two overlapping SHARED allocations are normal. | Keeps the two anomaly types separable so detection can be evaluated per type. |
| A-17 | Should the database reject anomalies? | **No for loaded/imported data**: the DB enforces structural integrity (PK, FK, enum, check constraints, date order) but business anomalies must be *stored* so they can be detected. **Yes for interactive API writes**: new allocations that would over-allocate or conflict are rejected with `409` unless an `override_reason` is supplied, which is audited (BR-ALC-005). | Preserves anomalous source records for testing while protecting new data. |
| A-18 | How are allocations linked to demand? | An allocation references **project + role + date range** (not a weekly demand line). For each week, its hours are applied to that project's lines for that role, in line order, for the lines the employee is eligible for (BR-GAP-002). | Allocations span many weeks; demand lines are weekly. |

## Gaps and recommendations

| ID | Ambiguity | Decision | Why |
|---|---|---|---|
| A-19 | Definition of a skill gap | `gap_hours = max(0, demand − committed eligible coverage)` per project × role × primary skill × week (BR-GAP-005). Hours allocated to *ineligible* employees count as **at-risk**, not covered. | "Gap" means "not covered by qualified, already-assigned people". |
| A-20 | How is double-counting prevented? | A **capacity ledger** per employee-week: every hour can be consumed once (by an allocation, a reallocation, or training). Gaps are processed in a deterministic priority order (BR-GAP-001, BR-GAP-004). | Directly required by the brief; also makes results reproducible. |
| A-21 | Hire vs train vs reallocate | Strategies run as ordered passes over all gaps: **REALLOCATE → TRAIN → HIRE** (BR-REC-001). Training needs lead time and trainee capacity; hiring needs a sustained gap (≥3 weeks, ≥20 h/week average). PERMANENT hire if the driving projects run ≥26 more weeks, else CONTRACT. | Cheapest/fastest action first; each decision has explicit thresholds. |
| A-22 | Are recommendations generated or labelled? | **Always derived by rules** from inputs. The generator shapes inputs (demand/capacity ratio, skill scarcity) so a realistic mix arises; it never assigns recommendation labels randomly. | Required by the brief ("do not independently randomize outcome labels"). |

## Forecasting

| ID | Ambiguity | Decision | Why |
|---|---|---|---|
| A-23 | Planned vs forecast vs actual | **Planned** = demand lines. **Forecast** = output of a forecasting method (stored per run). **Actual** = synthetic timesheet hours at project × role × week in `demand_actual`. | Three different quantities, three different storage places (BR-FCT-001). |
| A-24 | How are synthetic actuals produced without copying the plan? | From the *clean* baseline plan × per-project realization factor × weekly noise, with scope-change steps, cancellations (plan continues, actuals stop) and occasional unplanned work (06 doc §5). | Creates realistic, learnable deviations that a naive "forecast = plan" cannot fully capture. |
| A-25 | How are forecasts evaluated honestly? | **Back-test**: methods may only read actuals with week < `as_of_date` (BR-FCT-004). Weeks from `as_of_date` to horizon end are the **hold-out**. Metrics: MAE, WAPE, bias. | No look-ahead leakage. |
| A-26 | Machine learning? | **Not claimed.** Three deterministic baselines: NAIVE_PLAN, MOVING_AVERAGE, PLAN_RATIO (BR-FCT-003). | The brief forbids unearned ML claims. |

## Data, IDs and history

| ID | Ambiguity | Decision | Why |
|---|---|---|---|
| A-27 | Year segment in `PRJ-2026-…`, `ALLOC-2026-…` | Year = **year of the record's start date at creation**; the 6-digit number is a **global sequence** per prefix (not reset per year). IDs never change, even if dates are edited later. | Unique, sortable, immutable, and implementable with one PostgreSQL sequence. |
| A-28 | Multiple demand lines in one project-week | Suffix **`-NN`** (01–99): `DEM-PRJ-2026-000001-2026W01-03`. Numbers are assigned in order of creation; the generator creates lines sorted by role code, then primary skill code. | Deterministic and unique; supports duplicates as distinct records. |
| A-29 | How is history preserved? | (1) **Effective dating** on schedules, leave, allocations, training, demand weeks. (2) **Versioned rows** for employee skills (one current version; old versions closed with `effective_to`). (3) An **append-only `audit_event`** table (DB trigger blocks UPDATE/DELETE) with before/after JSON for every change. (4) **No hard deletes** of referenced records — deactivate/cancel instead. | Covers both "as it was on date X" and "who changed what". |
| A-30 | Where does ground truth live? | **Only in files** (`ground_truth.csv/json`) next to — never inside — the input data. It is **not loaded into the application database**; only the evaluation script reads it. | Makes leakage into the detection engine structurally impossible. |
| A-31 | Analysis results: computed on the fly or stored? | Stored per **`analysis_run`** (snapshot with parameters, rule version and rules-file hash). The API serves the latest successful run unless a `run_id` is given. | Results are reproducible, comparable and auditable. |
| A-32 | Numeric precision | Hours stored as `NUMERIC(7,2)`; engines compute with `Decimal`, round half-up to 2 decimals at storage/export boundaries; generator produces hours in 0.5 h steps. | Avoids float noise that would break checksums. |

## Technology

| ID | Ambiguity | Decision | Why |
|---|---|---|---|
| A-33 | Sync or async SQLAlchemy? | **Synchronous** SQLAlchemy 2.0 with `psycopg` 3; FastAPI runs sync handlers in a thread pool. | Simpler to learn and debug; analytics is CPU-bound anyway. |
| A-34 | Python version | Python **3.13** virtual environment (3.12+ supported). | Both are installed; 3.13 is the newest available here. |
| A-35 | Database engine (**revised in Phase 2**, user decision 2026-11-14) | **SQLite** is the active development database (`data/db/workforceiq.sqlite3`); the schema and migrations remain **PostgreSQL 17-compatible** and switching is configuration only (`WFIQ_DB_BACKEND=postgresql`). The PostgreSQL DDL is compiled offline in tests; a live PostgreSQL run is pending a server. | PostgreSQL was not installed and installing it needs administrator rights; SQLite needs nothing. Note: the original brief names PostgreSQL for Tier 3, so the final submission should ideally be verified on PostgreSQL once available. |
| A-36 | Synthetic names and text | Generated from small author-written word lists in the repo; emails use the reserved `example.com` domain. No external datasets. | No licensing or privacy issues (provenance in the source manifest, Phase 7). |
| A-37 | Authentication | Out of scope; `X-Actor` header (default `anonymous`) is written to audit events; CORS restricted to the frontend origin. | Hackathon scope; still keeps an audit trail. |

## Phase 2 decisions (database implementation)

| ID | Question | Decision | Why |
|---|---|---|---|
| A-38 | How are IDs issued for API-created records without PostgreSQL sequences? | A 22nd table **`id_sequence`** (prefix → last value), incremented in the caller's transaction (`SELECT … FOR UPDATE` on PostgreSQL). The seed loader raises it past the highest seeded number. | Portable across SQLite and PostgreSQL; still one global sequence per prefix (A-27). |
| A-39 | How are portable types handled? | `NUMERIC(p,s)` via a `DecimalType` that returns exact `Decimal` on both engines; timestamps always UTC-aware (`UTCDateTime`); `JSON` → `JSONB` on PostgreSQL with `none_as_null=True`; enums as `VARCHAR` + named `CHECK`. | Same behaviour on both engines; no float noise in hours. |
| A-40 | Constraints that SQLite and PostgreSQL express differently | Written per dialect in the migration: append-only `audit_event` (SQLite triggers / PostgreSQL trigger function), non-overlapping work schedules (SQLite triggers / PostgreSQL `EXCLUDE USING gist`). | Keeps the guarantee on both engines. |
| A-41 | Immutable identifiers | Primary keys and each model's `__immutable__` columns (e.g. a demand line's project/week/line) cannot change: an ORM `before_flush` guard raises `ImmutableFieldError`; foreign keys are `ON DELETE RESTRICT`. | Implements BR-VAL-007 in one place for all tables. |
| A-42 | Where do audit_event, id_sequence and dataset_metadata live? | In the shared persistence package `app/db` ("platform tables"), not in `reporting` or `domain`. | `domain` must stay framework-free, and every module writes audit events. |

## Phase 2 design corrections

Discovered while implementing `docs/05-data-model.md`; none changes an entity's meaning.

| # | Phase 1 text | Correction | Reason |
|---|---|---|---|
| C-1 | `demand_plan.week_start_date` "CHECK: ISODOW = 1" | Monday rule enforced in the domain layer (`calendar.week_start`) and BR-VAL checks, not by a DB CHECK. | No expression is valid on both SQLite and PostgreSQL. |
| C-2 | "PostgreSQL sequences" for IDs | `id_sequence` table (A-38). | Portability. |
| C-3 | "Every business table has created_at and updated_at" | Immutable run outputs (`capacity_snapshot`, `forecast_result`, `gap_analysis`, `recommendation_gap_link`) and key/value platform tables carry no timestamps; their time is the run's `started_at`/`finished_at`. | They are never updated, so `updated_at` would be meaningless. |
| C-4 | ID format CHECKs | DB checks prefix + exact length (portable `LIKE` + `length()`); digit-level validation is in `app.domain.ids`. | Regex syntax differs between engines. |
| C-5 | `audit_event.entity_id` length | 120 characters (was unspecified). | Composite keys such as `run|employee|week` are joined with `|`. |

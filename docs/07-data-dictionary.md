# 07 — Data Dictionary

> **Generated** from the SQLAlchemy models by `python -m app.db.data_dictionary`. Do not edit by hand — a unit test fails if this file is out of date.

Conventions: *Req* = NOT NULL. *Type (PostgreSQL)* is the target type; *SQLite* is the storage type used in development (decision A-35). Hours are stored with 2 decimals and handled as exact `Decimal` values in Python. Named CHECK constraints are listed per table; the *Validation* column names the constraints that involve the field. Foreign keys use `ON DELETE RESTRICT`. Rules that span rows or need the calendar (e.g. one PRIMARY skill per demand line, week_start_date is a Monday) are enforced in the domain/service layer and the BR-VAL checks.

## Entities

| # | Entity | Table | Kind | Columns | Description |
|---|---|---|---|---|---|
| 1 | Allocation | `allocation` | Mandatory | 12 | Employee assignments. Over-allocation and overlaps are detected, not prevented, at DB level (A-17). |
| 2 | Availability | `availability` | Mandatory | 11 | Work schedules (weekly hours) and leave (reduces capacity). |
| 3 | DemandPlan | `demand_plan` | Mandatory | 13 | Weekly demand lines. The business key is NOT unique on purpose: duplicates are detected, not prevented (BR-DEM-004). |
| 4 | Employee | `employee` | Mandatory | 12 | Employees (synthetic). Working hours live in availability (A-06). |
| 5 | EmployeeSkill | `employee_skill` | Mandatory | 12 | Employee skill profile versions; one current version per employee+skill. |
| 6 | GapAnalysis | `gap_analysis` | Mandatory | 19 | Coverage and gap per run x project x role x primary skill x week. |
| 7 | Project | `project` | Mandatory | 11 | Client or internal projects that create demand. |
| 8 | Role | `role` | Mandatory | 8 | Job roles employees hold and demand lines request. |
| 9 | Skill | `skill` | Mandatory | 10 | Skills that employees hold and demand lines require. |
| 10 | Training | `training` | Mandatory | 14 | Training activities; consume capacity (BR-CAP-006). |
| 11 | AnalysisRun | `analysis_run` | Supporting | 16 | One execution of forecasting / gap analysis / detection (A-31). |
| 12 | AuditEvent | `audit_event` | Supporting | 10 | Immutable audit trail of every change to business records (A-29). |
| 13 | CapacitySnapshot | `capacity_snapshot` | Supporting | 11 | Per employee-week capacity facts (BR-CAP-003..009, BR-UTL-001/002). |
| 14 | DatasetMetadata | `dataset_metadata` | Supporting | 2 | Facts about the loaded synthetic dataset. |
| 15 | DemandActual | `demand_actual` | Supporting | 9 | Actual hours. Forecast methods may read only weeks before the forecast origin (BR-FCT-004). |
| 16 | DemandSkillRequirement | `demand_skill_requirement` | Supporting | 6 | Skills required by a demand line (1 PRIMARY, 0-2 SECONDARY). |
| 17 | ExceptionFinding | `exception_finding` | Supporting | 14 | Detected anomalies (BR-UTL-004, BR-SKL-004, BR-DEM-004, BR-ALC-003). |
| 18 | ForecastResult | `forecast_result` | Supporting | 7 | Forecast demand per run, method, project, role and week (BR-FCT-002). |
| 19 | IdSequence | `id_sequence` | Supporting | 2 | Last issued sequence number per ID prefix (EMP, PRJ, ALLOC, ...). |
| 20 | Recommendation | `recommendation` | Supporting | 21 | Explainable REALLOCATE / TRAIN / HIRE actions (BR-REC-001..006). |
| 21 | RecommendationGapLink | `recommendation_gap_link` | Supporting | 3 | Which gap rows a recommendation addresses, and by how many hours. |
| 22 | RoleSkill | `role_skill` | Supporting | 6 | Bridge role <-> skill: skills a role is expected to have. |

## 1. Allocation (`allocation`)

Employee assignments. Over-allocation and overlaps are detected, not prevented, at DB level (A-17).

**Primary key:** `allocation_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `allocation_id` | VARCHAR(17) | VARCHAR(17) | Yes | — | — | PK | Yes (PK) | — | `ck_allocation_allocation_id_format` | Immutable ID, ALLOC-<start year>-000001. |
| `employee_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → employee.employee_id | No | — | — | Allocated employee. |
| `project_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | FK → project.project_id | No | — | — | Project. |
| `role_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → role.role_id | No | — | — | Role played on the project. |
| `start_date` | DATE | DATE | Yes | — | — | — | No | — | `ck_allocation_date_order` | First day (inclusive). |
| `end_date` | DATE | DATE | Yes | — | — | — | No | — | `ck_allocation_date_order` | Last day (inclusive). |
| `hours_per_week` | NUMERIC(5, 2) | NUMERIC(5, 2) | Yes | — | — | — | No | hours | `ck_allocation_hours_per_week_range` | Booked hours per full week; prorated by working days (BR-CAP-008). |
| `allocation_type` | VARCHAR(9) | VARCHAR(9) | Yes | — | DEDICATED, SHARED | — | No | — | value in allowed list (CHECK) | DEDICATED = exclusive (BR-ALC-003); SHARED = may overlap. |
| `status` | VARCHAR(9) | VARCHAR(9) | Yes | — | PROPOSED, CONFIRMED, COMPLETED, CANCELLED | — | No | — | value in allowed list (CHECK) | Lifecycle status (BR-ALC-002). |
| `notes` | TEXT | TEXT | No | — | — | — | No | — | — | Optional note. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_allocation_allocation_id_format`: `allocation_id LIKE 'ALLOC-%' AND length(allocation_id) = 17`
- `ck_allocation_date_order`: `end_date IS NULL OR end_date >= start_date`
- `ck_allocation_hours_per_week_range`: `hours_per_week > 0 AND hours_per_week <= 60`

**Indexes**

- `ix_allocation_employee_dates`: (employee_id, start_date, end_date)
- `ix_allocation_project_role`: (project_id, role_id)
- `ix_allocation_status`: (status)

## 2. Availability (`availability`)

Work schedules (weekly hours) and leave (reduces capacity).

**Primary key:** `availability_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `availability_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | PK | Yes (PK) | — | `ck_availability_availability_id_format` | Immutable ID, AVL-<start year>-000001. |
| `employee_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → employee.employee_id | No | — | — | Employee. |
| `availability_type` | VARCHAR(14) | VARCHAR(14) | Yes | — | WORK_SCHEDULE, ANNUAL_LEAVE, SICK_LEAVE, PARENTAL_LEAVE, UNPAID_LEAVE, OTHER_ABSENCE | — | No | — | value in allowed list (CHECK), `ck_availability_type_fields` | WORK_SCHEDULE or a leave type. |
| `start_date` | DATE | DATE | Yes | — | — | — | No | — | `ck_availability_date_order` | First day (inclusive). |
| `end_date` | DATE | DATE | No | — | — | — | No | — | `ck_availability_date_order`, `ck_availability_type_fields` | Last day (inclusive); null only for an open-ended work schedule. |
| `weekly_hours` | NUMERIC(5, 2) | NUMERIC(5, 2) | No | — | — | — | No | hours | `ck_availability_type_fields` | Contracted hours per week; WORK_SCHEDULE only, 8-40 (BR-CAP-004). |
| `hours_per_day` | NUMERIC(4, 2) | NUMERIC(4, 2) | No | — | — | — | No | hours | `ck_availability_type_fields` | Partial-day leave hours; null = full day (BR-CAP-005). Leave only. |
| `status` | VARCHAR(9) | VARCHAR(9) | Yes | — | REQUESTED, APPROVED, REJECTED, CANCELLED | — | No | — | value in allowed list (CHECK) | Only APPROVED rows affect capacity. |
| `reason` | VARCHAR(200) | VARCHAR(200) | No | — | — | — | No | — | — | Optional note. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_availability_availability_id_format`: `availability_id LIKE 'AVL-%' AND length(availability_id) = 15`
- `ck_availability_date_order`: `end_date IS NULL OR end_date >= start_date`
- `ck_availability_type_fields`: `(availability_type = 'WORK_SCHEDULE' AND weekly_hours IS NOT NULL AND weekly_hours >= 8 AND weekly_hours <= 40 AND hours_per_day IS NULL) OR (availability_type <> 'WORK_SCHEDULE' AND weekly_hours IS NULL AND end_date IS NOT NULL AND (hours_per_day IS NULL OR (hours_per_day > 0 AND hours_per_day <= 8)))`

**Indexes**

- `ix_availability_availability_type`: (availability_type)
- `ix_availability_employee_dates`: (employee_id, start_date, end_date)

## 3. DemandPlan (`demand_plan`)

Weekly demand lines. The business key is NOT unique on purpose: duplicates are detected, not prevented (BR-DEM-004).

**Primary key:** `demand_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `demand_id` | VARCHAR(40) | VARCHAR(40) | Yes | — | — | PK | Yes (PK) | — | `ck_demand_plan_demand_id_format` | Immutable ID, DEM-<project_id>-<ISO year>W<ISO week>-<line> (BR-DEM-005). |
| `project_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | FK → project.project_id | in `uq_demand_plan_line` | — | `ck_demand_plan_demand_id_format` | Project. |
| `role_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → role.role_id | No | — | — | Requested role. |
| `iso_year` | SMALLINT | SMALLINT | Yes | — | — | — | in `uq_demand_plan_line` | — | `ck_demand_plan_iso_year_range` | ISO-8601 year of the week. |
| `iso_week` | SMALLINT | SMALLINT | Yes | — | — | — | in `uq_demand_plan_line` | — | `ck_demand_plan_iso_week_range` | ISO-8601 week number 1-53. |
| `week_start_date` | DATE | DATE | Yes | — | — | — | No | — | — | Monday of the ISO week (validated in the domain layer). |
| `line_no` | SMALLINT | SMALLINT | Yes | — | — | — | in `uq_demand_plan_line` | — | `ck_demand_plan_line_no_range` | 1-based line number within project + week. |
| `required_hours` | NUMERIC(7, 2) | NUMERIC(7, 2) | Yes | — | — | — | No | hours | `ck_demand_plan_hours_within_headcount`, `ck_demand_plan_required_hours_positive` | Planned hours for the week. |
| `headcount` | SMALLINT | SMALLINT | Yes | — | — | — | No | people | `ck_demand_plan_headcount_positive`, `ck_demand_plan_hours_within_headcount` | Number of people expected to share the hours. |
| `status` | VARCHAR(9) | VARCHAR(9) | Yes | — | DRAFT, SUBMITTED, APPROVED, REJECTED, CANCELLED | — | No | — | value in allowed list (CHECK) | Lifecycle status (BR-DEM-002); counted statuses in BR-DEM-003. |
| `source` | VARCHAR(12) | VARCHAR(12) | Yes | — | PROJECT_PLAN, MANUAL, IMPORT | — | No | — | value in allowed list (CHECK) | Where the line came from. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_demand_plan_demand_id_format`: `demand_id LIKE 'DEM-' \|\| project_id \|\| '-%' AND length(demand_id) = 30`
- `ck_demand_plan_headcount_positive`: `headcount >= 1`
- `ck_demand_plan_hours_within_headcount`: `required_hours <= headcount * 40`
- `ck_demand_plan_iso_week_range`: `iso_week >= 1 AND iso_week <= 53`
- `ck_demand_plan_iso_year_range`: `iso_year >= 2000 AND iso_year <= 2100`
- `ck_demand_plan_line_no_range`: `line_no >= 1 AND line_no <= 99`
- `ck_demand_plan_required_hours_positive`: `required_hours > 0`

**Indexes**

- `ix_demand_plan_project_week`: (project_id, week_start_date)
- `ix_demand_plan_role_week`: (role_id, week_start_date)
- `ix_demand_plan_status`: (status)
- `uq_demand_plan_line`: UNIQUE (project_id, iso_year, iso_week, line_no)

## 4. Employee (`employee`)

Employees (synthetic). Working hours live in availability (A-06).

**Primary key:** `employee_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `employee_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | PK | Yes (PK) | — | `ck_employee_employee_id_format` | Immutable employee ID, EMP-000001. |
| `first_name` | VARCHAR(60) | VARCHAR(60) | Yes | — | — | — | No | — | — | Given name (synthetic). |
| `last_name` | VARCHAR(60) | VARCHAR(60) | Yes | — | — | — | No | — | — | Family name (synthetic). |
| `email` | VARCHAR(254) | VARCHAR(254) | Yes | — | — | — | Yes | — | — | Unique email; @example.com in synthetic data. |
| `role_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → role.role_id | No | — | — | Primary role. |
| `seniority` | VARCHAR(9) | VARCHAR(9) | Yes | — | JUNIOR, MID, SENIOR, LEAD, PRINCIPAL | — | No | — | value in allowed list (CHECK) | Seniority grade. |
| `location` | VARCHAR(60) | VARCHAR(60) | Yes | — | — | — | No | — | — | Work location (synthetic city). |
| `hire_date` | DATE | DATE | Yes | — | — | — | No | — | `ck_employee_employment_dates` | First working day. |
| `termination_date` | DATE | DATE | No | — | — | — | No | — | `ck_employee_employment_dates`, `ck_employee_terminated_has_date` | Last working day; null while employed. |
| `status` | VARCHAR(13) | VARCHAR(13) | Yes | — | PENDING_START, ACTIVE, TERMINATED | — | No | — | value in allowed list (CHECK), `ck_employee_terminated_has_date` | Lifecycle status; must agree with dates (BR-EMP-001). |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_employee_employee_id_format`: `employee_id LIKE 'EMP-%' AND length(employee_id) = 10`
- `ck_employee_employment_dates`: `termination_date IS NULL OR termination_date >= hire_date`
- `ck_employee_terminated_has_date`: `status <> 'TERMINATED' OR termination_date IS NOT NULL`

**Indexes**

- `ix_employee_role_id`: (role_id)
- `ix_employee_status`: (status)

## 5. EmployeeSkill (`employee_skill`)

Employee skill profile versions; one current version per employee+skill.

**Primary key:** `employee_skill_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `employee_skill_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | PK | Yes (PK) | — | `ck_employee_skill_employee_skill_id_format` | Immutable version ID, ESK-000001. |
| `employee_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → employee.employee_id | in `uq_employee_skill_current` (partial); in `uq_employee_skill_version` | — | — | Employee holding the skill. |
| `skill_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → skill.skill_id | in `uq_employee_skill_current` (partial); in `uq_employee_skill_version` | — | — | Skill held. |
| `proficiency_level` | SMALLINT | SMALLINT | Yes | — | — | — | No | proficiency level (1-5) | `ck_employee_skill_proficiency_level_range` | 1 Awareness .. 5 Expert (BR-SKL-001). |
| `assessment_source` | VARCHAR(13) | VARCHAR(13) | Yes | — | SELF, MANAGER, ASSESSMENT, CERTIFICATION, TRAINING | — | No | — | value in allowed list (CHECK) | How the level was assessed. |
| `last_verified_date` | DATE | DATE | Yes | — | — | — | No | — | `ck_employee_skill_expiry_after_verified` | Date the level was last verified (freshness, BR-SKL-002). |
| `expiry_date` | DATE | DATE | No | — | — | — | No | — | `ck_employee_skill_expiry_after_verified` | Certificate expiry; required for certification skills (BR-SKL-005). |
| `recorded_status` | VARCHAR(20) | VARCHAR(20) | Yes | — | CURRENT, EXPIRED, PENDING_VERIFICATION | — | No | — | value in allowed list (CHECK) | Status flag from the source system; informational only (BR-SKL-003). |
| `effective_from` | DATE | DATE | Yes | — | — | — | in `uq_employee_skill_version` | — | `ck_employee_skill_effective_dates` | First day this version applies. |
| `effective_to` | DATE | DATE | No | — | — | — | No | — | `ck_employee_skill_effective_dates` | Last day this version applies; null = current version. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_employee_skill_effective_dates`: `effective_to IS NULL OR effective_to >= effective_from`
- `ck_employee_skill_employee_skill_id_format`: `employee_skill_id LIKE 'ESK-%' AND length(employee_skill_id) = 10`
- `ck_employee_skill_expiry_after_verified`: `expiry_date IS NULL OR expiry_date > last_verified_date`
- `ck_employee_skill_proficiency_level_range`: `proficiency_level >= 1 AND proficiency_level <= 5`

**Indexes**

- `ix_employee_skill_current_skill_level`: (skill_id, proficiency_level) WHERE `effective_to IS NULL`
- `ix_employee_skill_employee_id`: (employee_id)
- `uq_employee_skill_current`: UNIQUE (employee_id, skill_id) WHERE `effective_to IS NULL`
- `uq_employee_skill_version`: UNIQUE (employee_id, skill_id, effective_from)

## 6. GapAnalysis (`gap_analysis`)

Coverage and gap per run x project x role x primary skill x week.

**Primary key:** `gap_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `gap_id` | VARCHAR(17) | VARCHAR(17) | Yes | — | — | PK | Yes (PK) | — | `ck_gap_analysis_gap_id_format` | Immutable ID, GAP-<run seq>-<seq>. |
| `run_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | FK → analysis_run.run_id | in `uq_gap_analysis_grain` | — | — | Run. |
| `project_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | FK → project.project_id | in `uq_gap_analysis_grain` | — | — | Project. |
| `role_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → role.role_id | in `uq_gap_analysis_grain` | — | — | Demanded role. |
| `skill_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → skill.skill_id | in `uq_gap_analysis_grain` | — | — | Primary skill (A-14). |
| `iso_year` | SMALLINT | SMALLINT | Yes | — | — | — | No | — | — | ISO-8601 year. |
| `iso_week` | SMALLINT | SMALLINT | Yes | — | — | — | No | — | `ck_gap_analysis_iso_week_range` | ISO-8601 week. |
| `week_start_date` | DATE | DATE | Yes | — | — | — | in `uq_gap_analysis_grain` | — | — | Monday of the ISO week. |
| `demand_hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_gap_analysis_committed_le_demand`, `ck_gap_analysis_demand_positive`, `ck_gap_analysis_gap_identity` | Counted, de-duplicated demand (BR-DEM-003/004). |
| `committed_hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_gap_analysis_committed_le_demand`, `ck_gap_analysis_gap_identity`, `ck_gap_analysis_non_negative_hours` | Covered by eligible allocated employees (BR-GAP-002). |
| `at_risk_hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_gap_analysis_non_negative_hours` | Allocated but ineligible (BR-GAP-003). |
| `gap_hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_gap_analysis_gap_identity`, `ck_gap_analysis_non_negative_hours`, `ck_gap_analysis_resolution_identity` | demand - committed (BR-GAP-005). |
| `coverage_ratio` | NUMERIC(6, 4) | NUMERIC(6, 4) | Yes | — | — | — | No | ratio (0-1) | `ck_gap_analysis_coverage_range` | committed / demand. |
| `reallocated_hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_gap_analysis_non_negative_hours`, `ck_gap_analysis_resolution_identity` | Gap resolved by REALLOCATE (BR-REC-002). |
| `trained_hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_gap_analysis_non_negative_hours`, `ck_gap_analysis_resolution_identity` | Gap resolved by TRAIN (BR-REC-003). |
| `hire_hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_gap_analysis_non_negative_hours`, `ck_gap_analysis_resolution_identity` | Gap resolved by HIRE (BR-REC-004). |
| `unresolved_hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_gap_analysis_non_negative_hours`, `ck_gap_analysis_resolution_identity` | Gap left after all strategies. |
| `severity` | VARCHAR(8) | VARCHAR(8) | Yes | — | NONE, LOW, MEDIUM, HIGH, CRITICAL | — | No | — | value in allowed list (CHECK) | Severity band (BR-GAP-006). |
| `source_demand_ids` | JSONB | JSON | Yes | — | — | — | No | — | — | Demand lines aggregated into this row. |

**CHECK constraints**

- `ck_gap_analysis_committed_le_demand`: `committed_hours <= demand_hours + 0.01`
- `ck_gap_analysis_coverage_range`: `coverage_ratio >= 0 AND coverage_ratio <= 1`
- `ck_gap_analysis_demand_positive`: `demand_hours > 0`
- `ck_gap_analysis_gap_id_format`: `gap_id LIKE 'GAP-%' AND length(gap_id) = 17`
- `ck_gap_analysis_gap_identity`: `ABS(gap_hours - (demand_hours - committed_hours)) <= 0.01`
- `ck_gap_analysis_iso_week_range`: `iso_week >= 1 AND iso_week <= 53`
- `ck_gap_analysis_non_negative_hours`: `committed_hours >= 0 AND at_risk_hours >= 0 AND gap_hours >= 0 AND reallocated_hours >= 0 AND trained_hours >= 0 AND hire_hours >= 0 AND unresolved_hours >= 0`
- `ck_gap_analysis_resolution_identity`: `ABS(reallocated_hours + trained_hours + hire_hours + unresolved_hours - gap_hours) <= 0.01`

**Indexes**

- `ix_gap_analysis_run_role_skill`: (run_id, role_id, skill_id)
- `ix_gap_analysis_run_week`: (run_id, week_start_date)
- `uq_gap_analysis_grain`: UNIQUE (run_id, project_id, role_id, skill_id, week_start_date)

## 7. Project (`project`)

Client or internal projects that create demand.

**Primary key:** `project_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `project_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | PK | Yes (PK) | — | `ck_project_project_id_format` | Immutable ID, PRJ-<start year>-000001. |
| `name` | VARCHAR(150) | VARCHAR(150) | Yes | — | — | — | No | — | — | Project name (synthetic). |
| `client_name` | VARCHAR(150) | VARCHAR(150) | No | — | — | — | No | — | — | Client name (synthetic); null for internal projects. |
| `business_unit` | VARCHAR(60) | VARCHAR(60) | Yes | — | — | — | No | — | — | Owning business unit. |
| `priority` | VARCHAR(8) | VARCHAR(8) | Yes | — | CRITICAL, HIGH, MEDIUM, LOW | — | No | — | value in allowed list (CHECK) | Processing order for gap analysis (BR-PRJ-002). |
| `status` | VARCHAR(9) | VARCHAR(9) | Yes | — | PROPOSED, APPROVED, ACTIVE, ON_HOLD, COMPLETED, CANCELLED | — | No | — | value in allowed list (CHECK), `ck_project_closed_date_status` | Lifecycle status (BR-PRJ-001). |
| `start_date` | DATE | DATE | Yes | — | — | — | No | — | `ck_project_closed_after_start`, `ck_project_project_dates` | Planned start (inclusive). |
| `end_date` | DATE | DATE | Yes | — | — | — | No | — | `ck_project_project_dates` | Planned end (inclusive). |
| `closed_date` | DATE | DATE | No | — | — | — | No | — | `ck_project_closed_after_start`, `ck_project_closed_date_status` | Set iff status is COMPLETED or CANCELLED. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_project_closed_after_start`: `closed_date IS NULL OR closed_date >= start_date`
- `ck_project_closed_date_status`: `(status IN ('COMPLETED', 'CANCELLED') AND closed_date IS NOT NULL) OR (status NOT IN ('COMPLETED', 'CANCELLED') AND closed_date IS NULL)`
- `ck_project_project_dates`: `end_date IS NULL OR end_date >= start_date`
- `ck_project_project_id_format`: `project_id LIKE 'PRJ-%' AND length(project_id) = 15`

**Indexes**

- `ix_project_priority`: (priority)
- `ix_project_status`: (status)

## 8. Role (`role`)

Job roles employees hold and demand lines request.

**Primary key:** `role_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `role_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | PK | Yes (PK) | — | `ck_role_role_id_format` | Immutable role ID, ROL-000001. |
| `code` | VARCHAR(40) | VARCHAR(40) | Yes | — | — | — | Yes | — | — | Upper snake-case code, e.g. BACKEND_ENGINEER. |
| `name` | VARCHAR(100) | VARCHAR(100) | Yes | — | — | — | Yes | — | — | Display name. |
| `role_family` | VARCHAR(11) | VARCHAR(11) | Yes | — | ENGINEERING, DATA, CLOUD_INFRA, QUALITY, DESIGN, PRODUCT, DELIVERY, SECURITY | — | No | — | value in allowed list (CHECK) | Family used for eligibility (BR-SKL-006: same family required). |
| `description` | TEXT | TEXT | No | — | — | — | No | — | — | Free-text description. |
| `is_active` | BOOLEAN | BOOLEAN | Yes | DB: `true` | true, false | — | No | — | — | False = deactivated role. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_role_role_id_format`: `role_id LIKE 'ROL-%' AND length(role_id) = 10`

## 9. Skill (`skill`)

Skills that employees hold and demand lines require.

**Primary key:** `skill_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `skill_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | PK | Yes (PK) | — | `ck_skill_skill_id_format` | Immutable skill ID, SKL-000001. |
| `code` | VARCHAR(60) | VARCHAR(60) | Yes | — | — | — | Yes | — | — | Unique skill code. |
| `name` | VARCHAR(120) | VARCHAR(120) | Yes | — | — | — | Yes | — | — | Display name. |
| `category` | VARCHAR(14) | VARCHAR(14) | Yes | — | PROGRAMMING, DATA_ANALYTICS, CLOUD, DEVOPS, SECURITY, TESTING, DESIGN, MANAGEMENT, ARCHITECTURE, DOMAIN | — | No | — | value in allowed list (CHECK) | Skill category. |
| `requires_certification` | BOOLEAN | BOOLEAN | Yes | DB: `false` | true, false | — | No | — | `ck_skill_certification_validity` | True = proficiency expires (BR-SKL-005). |
| `validity_months` | SMALLINT | SMALLINT | No | — | — | — | No | months | `ck_skill_certification_validity`, `ck_skill_validity_months_range` | Certificate validity; required iff requires_certification (BR-SKL-005). |
| `description` | TEXT | TEXT | No | — | — | — | No | — | — | Free-text description. |
| `is_active` | BOOLEAN | BOOLEAN | Yes | DB: `true` | true, false | — | No | — | — | False = deactivated skill. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_skill_certification_validity`: `(requires_certification AND validity_months IS NOT NULL) OR (NOT requires_certification AND validity_months IS NULL)`
- `ck_skill_skill_id_format`: `skill_id LIKE 'SKL-%' AND length(skill_id) = 10`
- `ck_skill_validity_months_range`: `validity_months IS NULL OR (validity_months >= 1 AND validity_months <= 60)`

## 10. Training (`training`)

Training activities; consume capacity (BR-CAP-006).

**Primary key:** `training_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `training_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | PK | Yes (PK) | — | `ck_training_training_id_format` | Immutable ID, TRN-<start year>-000001. |
| `employee_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → employee.employee_id | No | — | — | Trainee. |
| `skill_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → skill.skill_id | No | — | — | Skill trained. |
| `recommendation_id` | VARCHAR(17) | VARCHAR(17) | No | — | — | FK → recommendation.recommendation_id | No | — | — | TRAIN recommendation this training implements, if any (BR-REC-006). |
| `outcome_employee_skill_id` | VARCHAR(10) | VARCHAR(10) | No | — | — | FK → employee_skill.employee_skill_id | Yes | — | `ck_training_outcome_only_when_completed` | Skill version created on completion (BR-TRN-002). |
| `training_type` | VARCHAR(15) | VARCHAR(15) | Yes | — | COURSE, CERTIFICATION, RECERTIFICATION, MENTORING | — | No | — | value in allowed list (CHECK) | Kind of training. |
| `target_proficiency` | SMALLINT | SMALLINT | Yes | — | — | — | No | proficiency level (1-5) | `ck_training_target_proficiency_range` | Level reached on completion. |
| `start_date` | DATE | DATE | Yes | — | — | — | No | — | `ck_training_completion_after_start`, `ck_training_date_order` | First day (inclusive). |
| `end_date` | DATE | DATE | Yes | — | — | — | No | — | `ck_training_date_order` | Last day (inclusive). |
| `hours_per_week` | NUMERIC(5, 2) | NUMERIC(5, 2) | Yes | — | — | — | No | hours | `ck_training_hours_per_week_range` | Weekly time spent; deducted from capacity. |
| `status` | VARCHAR(11) | VARCHAR(11) | Yes | — | PLANNED, IN_PROGRESS, COMPLETED, CANCELLED | — | No | — | value in allowed list (CHECK), `ck_training_completion_date_status`, `ck_training_outcome_only_when_completed` | Lifecycle status (BR-TRN-001). |
| `completion_date` | DATE | DATE | No | — | — | — | No | — | `ck_training_completion_after_start`, `ck_training_completion_date_status` | Required iff status is COMPLETED. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_training_completion_after_start`: `completion_date IS NULL OR completion_date >= start_date`
- `ck_training_completion_date_status`: `(status = 'COMPLETED' AND completion_date IS NOT NULL) OR (status <> 'COMPLETED' AND completion_date IS NULL)`
- `ck_training_date_order`: `end_date IS NULL OR end_date >= start_date`
- `ck_training_hours_per_week_range`: `hours_per_week > 0 AND hours_per_week <= 40`
- `ck_training_outcome_only_when_completed`: `outcome_employee_skill_id IS NULL OR status = 'COMPLETED'`
- `ck_training_target_proficiency_range`: `target_proficiency >= 1 AND target_proficiency <= 5`
- `ck_training_training_id_format`: `training_id LIKE 'TRN-%' AND length(training_id) = 15`

**Indexes**

- `ix_training_employee_id`: (employee_id)
- `ix_training_skill_id`: (skill_id)
- `ix_training_status`: (status)

## 11. AnalysisRun (`analysis_run`)

One execution of forecasting / gap analysis / detection (A-31).

**Primary key:** `run_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `run_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | PK | Yes (PK) | — | `ck_analysis_run_run_id_format` | Immutable ID, RUN-<as_of year>-000001. |
| `run_type` | VARCHAR(19) | VARCHAR(19) | Yes | — | FORECAST, GAP_ANALYSIS, EXCEPTION_DETECTION, FULL_PIPELINE | — | No | — | value in allowed list (CHECK) | Kind of run. |
| `status` | VARCHAR(9) | VARCHAR(9) | Yes | — | RUNNING, SUCCEEDED, FAILED | — | No | — | value in allowed list (CHECK), `ck_analysis_run_error_only_on_failure`, `ck_analysis_run_finished_at_status` | RUNNING -> SUCCEEDED \| FAILED. |
| `as_of_date` | DATE | DATE | Yes | — | — | — | No | — | — | 'Today' for status derivation and forecast origin (A-02). |
| `period_start` | DATE | DATE | Yes | — | — | — | No | — | `ck_analysis_run_period` | First analysed week (Monday). |
| `period_end` | DATE | DATE | Yes | — | — | — | No | — | `ck_analysis_run_period` | Last analysed day. |
| `rules_version` | VARCHAR(20) | VARCHAR(20) | Yes | — | — | — | No | — | — | business_rules.toml version. |
| `rules_sha256` | VARCHAR(64) | VARCHAR(64) | Yes | — | — | — | No | — | `ck_analysis_run_rules_sha256_length` | SHA-256 of business_rules.toml used (traceability). |
| `parameters` | JSONB | JSON | Yes | — | — | — | No | — | — | Request parameters, e.g. demand basis and method. |
| `summary` | JSONB | JSON | No | — | — | — | No | — | — | Headline metrics (e.g. MAE/WAPE, counts). |
| `started_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | — | — | — | No | — | — | Start time (UTC). |
| `finished_at` | TIMESTAMP WITH TIME ZONE | DATETIME | No | — | — | — | No | — | `ck_analysis_run_finished_at_status` | End time (UTC); null while RUNNING. |
| `error_message` | TEXT | TEXT | No | — | — | — | No | — | `ck_analysis_run_error_only_on_failure` | Failure reason (FAILED only). |
| `triggered_by` | VARCHAR(100) | VARCHAR(100) | Yes | — | — | — | No | — | — | Actor who started the run. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_analysis_run_error_only_on_failure`: `status = 'FAILED' OR error_message IS NULL`
- `ck_analysis_run_finished_at_status`: `(status = 'RUNNING' AND finished_at IS NULL) OR (status <> 'RUNNING' AND finished_at IS NOT NULL)`
- `ck_analysis_run_period`: `period_end IS NULL OR period_end >= period_start`
- `ck_analysis_run_rules_sha256_length`: `length(rules_sha256) = 64`
- `ck_analysis_run_run_id_format`: `run_id LIKE 'RUN-%' AND length(run_id) = 15`

**Indexes**

- `ix_analysis_run_type_status`: (run_type, status)

## 12. AuditEvent (`audit_event`)

Immutable audit trail of every change to business records (A-29).

**Primary key:** `audit_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `audit_id` | BIGINT | INTEGER | Yes | identity (auto-increment) | — | PK | Yes (PK) | — | — | Monotonic event number. |
| `occurred_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the change happened (UTC). |
| `actor` | VARCHAR(100) | VARCHAR(100) | Yes | — | — | — | No | — | — | Who made the change (X-Actor). |
| `request_id` | VARCHAR(64) | VARCHAR(64) | No | — | — | — | No | — | — | Correlation ID of the HTTP request, if any. |
| `entity_type` | VARCHAR(40) | VARCHAR(40) | Yes | — | — | — | No | — | — | Table name of the record. |
| `entity_id` | VARCHAR(120) | VARCHAR(120) | Yes | — | — | — | No | — | — | Primary key of the record. |
| `action` | VARCHAR(13) | VARCHAR(13) | Yes | — | CREATE, UPDATE, STATUS_CHANGE, DELETE | — | No | — | value in allowed list (CHECK), `ck_audit_event_state_by_action` | Kind of change. |
| `before_state` | JSONB | JSON | No | — | — | — | No | — | `ck_audit_event_state_by_action` | Column values before the change (null for CREATE). |
| `after_state` | JSONB | JSON | No | — | — | — | No | — | `ck_audit_event_state_by_action` | Column values after the change (null for DELETE). |
| `reason` | TEXT | TEXT | No | — | — | — | No | — | — | Why, e.g. override_reason (BR-ALC-005). |

**CHECK constraints**

- `ck_audit_event_state_by_action`: `(action = 'CREATE' AND before_state IS NULL AND after_state IS NOT NULL) OR (action = 'DELETE' AND after_state IS NULL AND before_state IS NOT NULL) OR (action IN ('UPDATE', 'STATUS_CHANGE') AND before_state IS NOT NULL AND after_state IS NOT NULL)`

**Indexes**

- `ix_audit_event_entity`: (entity_type, entity_id, occurred_at)

## 13. CapacitySnapshot (`capacity_snapshot`)

Per employee-week capacity facts (BR-CAP-003..009, BR-UTL-001/002).

**Primary key:** `run_id`, `employee_id`, `week_start_date`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `run_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | PK; FK → analysis_run.run_id | No | — | — | Run. |
| `employee_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | PK; FK → employee.employee_id | No | — | — | Employee. |
| `week_start_date` | DATE | DATE | Yes | — | — | PK | No | — | — | Monday of the ISO week. |
| `gross_hours` | NUMERIC(7, 2) | NUMERIC(7, 2) | Yes | — | — | — | No | hours | `ck_capacity_snapshot_net_identity`, `ck_capacity_snapshot_non_negative_hours` | Scheduled hours while employed (BR-CAP-003). |
| `leave_hours` | NUMERIC(7, 2) | NUMERIC(7, 2) | Yes | — | — | — | No | hours | `ck_capacity_snapshot_net_identity`, `ck_capacity_snapshot_non_negative_hours` | Approved leave deducted (BR-CAP-005). |
| `training_hours` | NUMERIC(7, 2) | NUMERIC(7, 2) | Yes | — | — | — | No | hours | `ck_capacity_snapshot_net_identity`, `ck_capacity_snapshot_non_negative_hours` | Training time deducted (BR-CAP-006). |
| `net_hours` | NUMERIC(7, 2) | NUMERIC(7, 2) | Yes | — | — | — | No | hours | `ck_capacity_snapshot_free_identity`, `ck_capacity_snapshot_net_identity`, `ck_capacity_snapshot_non_negative_hours`, `ck_capacity_snapshot_utilization_defined` | gross - leave - training (BR-CAP-007). |
| `allocated_hours` | NUMERIC(7, 2) | NUMERIC(7, 2) | Yes | — | — | — | No | hours | `ck_capacity_snapshot_free_identity`, `ck_capacity_snapshot_non_negative_hours` | Counted allocations, prorated (BR-CAP-008). |
| `free_hours` | NUMERIC(7, 2) | NUMERIC(7, 2) | Yes | — | — | — | No | hours | `ck_capacity_snapshot_free_identity` | net - allocated; negative = over-allocated (BR-CAP-009). |
| `utilization` | NUMERIC(6, 4) | NUMERIC(6, 4) | No | — | — | — | No | ratio | `ck_capacity_snapshot_utilization_defined` | allocated / net; null when net = 0 (BR-UTL-001). |
| `risk_band` | VARCHAR(14) | VARCHAR(14) | Yes | — | UNAVAILABLE, UNDER_UTILIZED, HEALTHY, HIGH, OVERALLOCATED | — | No | — | value in allowed list (CHECK) | Utilization band (BR-UTL-002). |

**CHECK constraints**

- `ck_capacity_snapshot_free_identity`: `ABS(free_hours - (net_hours - allocated_hours)) <= 0.01`
- `ck_capacity_snapshot_net_identity`: `ABS(net_hours - (gross_hours - leave_hours - training_hours)) <= 0.01`
- `ck_capacity_snapshot_non_negative_hours`: `gross_hours >= 0 AND leave_hours >= 0 AND training_hours >= 0 AND net_hours >= 0 AND allocated_hours >= 0`
- `ck_capacity_snapshot_utilization_defined`: `(net_hours = 0 AND utilization IS NULL) OR (net_hours > 0 AND utilization IS NOT NULL)`

**Indexes**

- `ix_capacity_snapshot_employee_id`: (employee_id)

## 14. DatasetMetadata (`dataset_metadata`)

Facts about the loaded synthetic dataset.

**Primary key:** `key`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `key` | VARCHAR(60) | VARCHAR(60) | Yes | — | — | PK | Yes (PK) | — | — | Metadata key. |
| `value` | TEXT | TEXT | Yes | — | — | — | No | — | — | Metadata value (text). |

## 15. DemandActual (`demand_actual`)

Actual hours. Forecast methods may read only weeks before the forecast origin (BR-FCT-004).

**Primary key:** `project_id`, `role_id`, `week_start_date`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `project_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | PK; FK → project.project_id | No | — | — | Project. |
| `role_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | PK; FK → role.role_id | No | — | — | Role. |
| `week_start_date` | DATE | DATE | Yes | — | — | PK | No | — | — | Monday of the ISO week. |
| `iso_year` | SMALLINT | SMALLINT | Yes | — | — | — | No | — | — | ISO-8601 year of the week. |
| `iso_week` | SMALLINT | SMALLINT | Yes | — | — | — | No | — | `ck_demand_actual_iso_week_range` | ISO-8601 week number. |
| `actual_hours` | NUMERIC(7, 2) | NUMERIC(7, 2) | Yes | — | — | — | No | hours | `ck_demand_actual_actual_hours_non_negative` | Hours actually worked. |
| `source` | VARCHAR(19) | VARCHAR(19) | Yes | — | SYNTHETIC_TIMESHEET, TIMESHEET | — | No | — | value in allowed list (CHECK) | Origin of the actuals. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_demand_actual_actual_hours_non_negative`: `actual_hours >= 0`
- `ck_demand_actual_iso_week_range`: `iso_week >= 1 AND iso_week <= 53`

**Indexes**

- `ix_demand_actual_role_week`: (role_id, week_start_date)

## 16. DemandSkillRequirement (`demand_skill_requirement`)

Skills required by a demand line (1 PRIMARY, 0-2 SECONDARY).

**Primary key:** `demand_id`, `skill_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `demand_id` | VARCHAR(40) | VARCHAR(40) | Yes | — | — | PK; FK → demand_plan.demand_id | Yes (partial) | — | — | Demand line. |
| `skill_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | PK; FK → skill.skill_id | No | — | — | Required skill. |
| `requirement_type` | VARCHAR(9) | VARCHAR(9) | Yes | — | PRIMARY, SECONDARY | — | No | — | value in allowed list (CHECK) | PRIMARY = mandatory, drives gaps; SECONDARY = preferred, affects ranking. |
| `min_proficiency` | SMALLINT | SMALLINT | Yes | — | — | — | No | proficiency level (1-5) | `ck_demand_skill_requirement_min_proficiency_range` | Minimum level for eligibility. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_demand_skill_requirement_min_proficiency_range`: `min_proficiency >= 1 AND min_proficiency <= 5`

**Indexes**

- `ix_demand_skill_requirement_skill_id`: (skill_id)
- `uq_demand_skill_requirement_one_primary`: UNIQUE (demand_id) WHERE `requirement_type = 'PRIMARY'`

## 17. ExceptionFinding (`exception_finding`)

Detected anomalies (BR-UTL-004, BR-SKL-004, BR-DEM-004, BR-ALC-003).

**Primary key:** `finding_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `finding_id` | VARCHAR(17) | VARCHAR(17) | Yes | — | — | PK | Yes (PK) | — | `ck_exception_finding_finding_id_format` | Immutable ID, EXC-<run seq>-<seq>. |
| `run_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | FK → analysis_run.run_id | No | — | — | Run. |
| `anomaly_type` | VARCHAR(32) | VARCHAR(32) | Yes | — | ALLOCATION_EXCEEDS_AVAILABILITY, EXPIRED_SKILL_TREATED_AS_CURRENT, DUPLICATE_DEMAND, OVERLAPPING_ALLOCATION_CONFLICT, STALE_SKILL | — | No | — | value in allowed list (CHECK) | Detected anomaly type. |
| `rule_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | — | No | — | `ck_exception_finding_rule_id_format` | Detecting business rule. |
| `entity_type` | VARCHAR(40) | VARCHAR(40) | Yes | — | — | — | No | — | — | Table of the primary record (e.g. employee_skill). |
| `entity_id` | VARCHAR(40) | VARCHAR(40) | Yes | — | — | — | No | — | — | ID of the primary record. |
| `week_start_date` | DATE | DATE | No | — | — | — | No | — | — | Affected week, for week-based anomalies. |
| `related_ids` | JSONB | JSON | Yes | — | — | — | No | — | — | Other records involved (e.g. both allocations). |
| `severity` | VARCHAR(8) | VARCHAR(8) | Yes | — | LOW, MEDIUM, HIGH, CRITICAL | — | No | — | value in allowed list (CHECK) | Severity. |
| `message` | TEXT | TEXT | Yes | — | — | — | No | — | — | Human-readable description. |
| `details` | JSONB | JSON | Yes | — | — | — | No | — | — | Numbers behind the finding (e.g. allocated vs net hours). |
| `status` | VARCHAR(12) | VARCHAR(12) | Yes | — | OPEN, ACKNOWLEDGED, RESOLVED, DISMISSED | — | No | — | value in allowed list (CHECK) | Review lifecycle. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_exception_finding_finding_id_format`: `finding_id LIKE 'EXC-%' AND length(finding_id) = 17`
- `ck_exception_finding_rule_id_format`: `rule_id LIKE 'BR-%' AND length(rule_id) = 10`

**Indexes**

- `ix_exception_finding_entity`: (entity_type, entity_id)
- `ix_exception_finding_run_type`: (run_id, anomaly_type)
- `ix_exception_finding_status`: (status)

## 18. ForecastResult (`forecast_result`)

Forecast demand per run, method, project, role and week (BR-FCT-002).

**Primary key:** `run_id`, `method`, `project_id`, `role_id`, `week_start_date`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `run_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | PK; FK → analysis_run.run_id | No | — | — | Run. |
| `method` | VARCHAR(14) | VARCHAR(14) | Yes | — | NAIVE_PLAN, MOVING_AVERAGE, PLAN_RATIO | PK | No | — | value in allowed list (CHECK) | Forecasting strategy (BR-FCT-003). |
| `project_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | PK; FK → project.project_id | No | — | — | Project. |
| `role_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | PK; FK → role.role_id | No | — | — | Role. |
| `week_start_date` | DATE | DATE | Yes | — | — | PK | No | — | — | Monday of the forecast week. |
| `planned_hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_forecast_result_non_negative_hours` | Planned (de-duplicated) hours used as input. |
| `forecast_hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_forecast_result_non_negative_hours` | Forecast hours. |

**CHECK constraints**

- `ck_forecast_result_non_negative_hours`: `planned_hours >= 0 AND forecast_hours >= 0`

**Indexes**

- `ix_forecast_result_run_role_week`: (run_id, role_id, week_start_date)

## 19. IdSequence (`id_sequence`)

Last issued sequence number per ID prefix (EMP, PRJ, ALLOC, ...).

**Primary key:** `prefix`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `prefix` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | PK | Yes (PK) | — | — | ID prefix, e.g. EMP or ALLOC. |
| `last_value` | INTEGER | INTEGER | Yes | — | — | — | No | — | `ck_id_sequence_last_value_non_negative` | Highest sequence number issued so far. |

**CHECK constraints**

- `ck_id_sequence_last_value_non_negative`: `last_value >= 0`

## 20. Recommendation (`recommendation`)

Explainable REALLOCATE / TRAIN / HIRE actions (BR-REC-001..006).

**Primary key:** `recommendation_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `recommendation_id` | VARCHAR(17) | VARCHAR(17) | Yes | — | — | PK | Yes (PK) | — | `ck_recommendation_recommendation_id_format` | Immutable ID, REC-<run seq>-<seq>. |
| `run_id` | VARCHAR(15) | VARCHAR(15) | Yes | — | — | FK → analysis_run.run_id | No | — | — | Run. |
| `recommendation_type` | VARCHAR(10) | VARCHAR(10) | Yes | — | REALLOCATE, TRAIN, HIRE | — | No | — | value in allowed list (CHECK), `ck_recommendation_reallocate_has_project`, `ck_recommendation_type_fields` | Action type. |
| `hire_type` | VARCHAR(9) | VARCHAR(9) | No | — | PERMANENT, CONTRACT | — | No | — | value in allowed list (CHECK), `ck_recommendation_type_fields` | PERMANENT or CONTRACT (HIRE only). |
| `role_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → role.role_id | No | — | — | Role addressed. |
| `skill_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | FK → skill.skill_id | No | — | — | Primary skill addressed. |
| `employee_id` | VARCHAR(10) | VARCHAR(10) | No | — | — | FK → employee.employee_id | No | — | `ck_recommendation_type_fields` | Employee to reallocate or train (not HIRE). |
| `project_id` | VARCHAR(15) | VARCHAR(15) | No | — | — | FK → project.project_id | No | — | `ck_recommendation_reallocate_has_project` | Receiving project (required for REALLOCATE). |
| `period_start` | DATE | DATE | Yes | — | — | — | No | — | `ck_recommendation_period` | First week covered (Monday). |
| `period_end` | DATE | DATE | Yes | — | — | — | No | — | `ck_recommendation_period` | Last day covered. |
| `hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_recommendation_hours_positive` | Hours reallocated / trained / to hire for. |
| `headcount` | SMALLINT | SMALLINT | No | — | — | — | No | people | `ck_recommendation_type_fields` | People to hire (HIRE only, BR-REC-004). |
| `rank` | SMALLINT | SMALLINT | Yes | — | — | — | No | — | `ck_recommendation_rank_positive` | Deterministic display order in run. |
| `strategy_name` | VARCHAR(40) | VARCHAR(40) | Yes | — | — | — | No | — | — | Strategy class that produced it. |
| `rule_ids` | JSONB | JSON | Yes | — | — | — | No | — | — | Business rules applied. |
| `explanation` | TEXT | TEXT | Yes | — | — | — | No | — | — | Human-readable reasoning. |
| `assumptions` | JSONB | JSON | Yes | — | — | — | No | — | — | Parameter values used. |
| `source_refs` | JSONB | JSON | Yes | — | — | — | No | — | — | Source records [{type, id}] (BR-REC-005). |
| `status` | VARCHAR(11) | VARCHAR(11) | Yes | — | PROPOSED, ACCEPTED, REJECTED, IMPLEMENTED | — | No | — | value in allowed list (CHECK) | Review lifecycle (BR-REC-006). |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_recommendation_hours_positive`: `hours > 0`
- `ck_recommendation_period`: `period_end IS NULL OR period_end >= period_start`
- `ck_recommendation_rank_positive`: `rank >= 1`
- `ck_recommendation_reallocate_has_project`: `recommendation_type <> 'REALLOCATE' OR project_id IS NOT NULL`
- `ck_recommendation_recommendation_id_format`: `recommendation_id LIKE 'REC-%' AND length(recommendation_id) = 17`
- `ck_recommendation_type_fields`: `(recommendation_type = 'HIRE' AND hire_type IS NOT NULL AND headcount >= 1 AND employee_id IS NULL) OR (recommendation_type <> 'HIRE' AND hire_type IS NULL AND headcount IS NULL AND employee_id IS NOT NULL)`

**Indexes**

- `ix_recommendation_run_type`: (run_id, recommendation_type)
- `ix_recommendation_status`: (status)

## 21. RecommendationGapLink (`recommendation_gap_link`)

Which gap rows a recommendation addresses, and by how many hours.

**Primary key:** `recommendation_id`, `gap_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `recommendation_id` | VARCHAR(17) | VARCHAR(17) | Yes | — | — | PK; FK → recommendation.recommendation_id | No | — | — | Recommendation. |
| `gap_id` | VARCHAR(17) | VARCHAR(17) | Yes | — | — | PK; FK → gap_analysis.gap_id | No | — | — | Gap row addressed. |
| `covered_hours` | NUMERIC(9, 2) | NUMERIC(9, 2) | Yes | — | — | — | No | hours | `ck_recommendation_gap_link_covered_hours_positive` | Gap hours this recommendation resolves. |

**CHECK constraints**

- `ck_recommendation_gap_link_covered_hours_positive`: `covered_hours > 0`

**Indexes**

- `ix_recommendation_gap_link_gap_id`: (gap_id)

## 22. RoleSkill (`role_skill`)

Bridge role <-> skill: skills a role is expected to have.

**Primary key:** `role_id`, `skill_id`

| Field | Type (PostgreSQL) | SQLite | Req | Default | Allowed values | Key | Unique | Units | Validation | Description |
|---|---|---|---|---|---|---|---|---|---|---|
| `role_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | PK; FK → role.role_id | No | — | — | Role. |
| `skill_id` | VARCHAR(10) | VARCHAR(10) | Yes | — | — | PK; FK → skill.skill_id | No | — | — | Skill. |
| `importance` | VARCHAR(10) | VARCHAR(10) | Yes | — | CORE, SUPPORTING | — | No | — | value in allowed list (CHECK) | CORE or SUPPORTING. |
| `typical_min_proficiency` | SMALLINT | SMALLINT | Yes | — | — | — | No | proficiency level (1-5) | `ck_role_skill_typical_min_proficiency_range` | Typical minimum level for the role. |
| `created_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was inserted (UTC). |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DATETIME | Yes | DB: `CURRENT_TIMESTAMP` | — | — | No | — | — | When the row was last modified (UTC). |

**CHECK constraints**

- `ck_role_skill_typical_min_proficiency_range`: `typical_min_proficiency >= 1 AND typical_min_proficiency <= 5`

**Indexes**

- `ix_role_skill_skill_id`: (skill_id)

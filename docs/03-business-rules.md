# 03 — Business Rules

Every rule has a stable ID `BR-<AREA>-<NNN>`. Rule IDs are:

- defined here (statement, formula, example),
- parameterised in [`backend/config/business_rules.toml`](../backend/config/business_rules.toml)
  (one table per rule — a unit test checks both lists are identical),
- stored on every recommendation and exception finding (`rule_ids`), so any output can be
  explained by pointing to the rules that produced it.

Notation: `w` = an ISO week, `d` = a working day (Mon–Fri) in `w`, `e` = an employee.
All quantities are **hours** unless stated otherwise. Parameter names in `code` are the keys in
the TOML file.

---

## CAP — Capacity

### BR-CAP-001 — Hours are the canonical capacity unit; FTE is derived from the standard week
`FTE = hours / (standard_weekly_hours × number_of_weeks)`; `standard_weekly_hours = 40`.
Hours are stored with `hours_decimal_places = 2`. Example: 60 h over 2 weeks = 0.75 FTE.

### BR-CAP-002 — Planning calendar uses ISO-8601 weeks with Monday–Friday working days
A week runs Monday–Sunday and is identified by ISO year + ISO week (`2026W01` = 2025-12-29 →
2026-01-04). Working days are `working_weekdays = [1..5]`. A week belongs to the month of its
Thursday (`month_assignment = ISO_THURSDAY`).

### BR-CAP-003 — Gross capacity comes from the effective work schedule while employed
For each working day `d`: if `hire_date ≤ d` and (`termination_date` is null or `d ≤ termination_date`)
and a `WORK_SCHEDULE` row is active on `d`, then `scheduled(d) = schedule.weekly_hours / 5`,
else `0`. `gross(e,w) = Σ_d scheduled(d)`.

### BR-CAP-004 — Work schedules allow part-time hours within a bounded range
`min_weekly_hours (8) ≤ weekly_hours ≤ max_weekly_hours (40)`. An employee is **PART_TIME** on a
date when the active schedule has `weekly_hours < standard_weekly_hours`, otherwise FULL_TIME.

### BR-CAP-005 — Approved leave reduces capacity, capped at scheduled hours per day
Only leave with status in `counted_leave_statuses` (APPROVED) counts. A leave row without
`hours_per_day` is a full day. `leave(d) = min(scheduled(d), Σ leave hours on d)` — overlapping
leave rows on the same day are never deducted twice. `leave(e,w) = Σ_d leave(d)`.

### BR-CAP-006 — Scheduled training time reduces capacity
For training with status in `counted_training_statuses` and `start_date ≤ d ≤ end_date`:
`training(d) = min(hours_per_week / 5, scheduled(d) − leave(d))`. Disabled when `enabled = false`.

### BR-CAP-007 — Net available hours = gross − leave − training, never negative
`net(e,w) = gross − leave − training ≥ 0` (guaranteed by the caps in BR-CAP-005/006).

### BR-CAP-008 — Allocated hours are prorated by working days and are not reduced by leave
For allocations with status in `counted_allocation_statuses` (CONFIRMED, COMPLETED):
`allocated(e,w) = Σ_alloc hours_per_week × (working days of w inside [start_date, end_date]) / 5`.
Leave does **not** reduce allocated hours (A-07).

### BR-CAP-009 — Free hours and the capacity reconciliation identity
`free(e,w) = net − allocated` (negative ⇒ over-allocated). Identity checked for every
employee-week: `|gross − leave − training − allocated − free| ≤ reconciliation_tolerance_hours`.

## EMP — Employee

### BR-EMP-001 — Employee lifecycle status must agree with hire and termination dates
Statuses: `PENDING_START → ACTIVE → TERMINATED`. At `as_of_date`: PENDING_START ⇔
`hire_date > as_of`; TERMINATED ⇔ `termination_date ≤ as_of`; otherwise ACTIVE.
`termination_date ≥ hire_date`.

### BR-EMP-002 — An employee is active in a week if employed on at least one working day
Only active employees contribute capacity or eligibility for that week.

## PRJ — Project

### BR-PRJ-001 — Project lifecycle transitions
`PROPOSED → APPROVED | CANCELLED`; `APPROVED → ACTIVE | ON_HOLD | CANCELLED`;
`ACTIVE → ON_HOLD | COMPLETED | CANCELLED`; `ON_HOLD → ACTIVE | CANCELLED`.
COMPLETED and CANCELLED are terminal.

### BR-PRJ-002 — Project priority ranking used for deterministic processing order
`priority_rank`: CRITICAL = 1, HIGH = 2, MEDIUM = 3, LOW = 4 (lower is processed first).

## UTL — Utilization

### BR-UTL-001 — Utilization = allocated hours / net available hours
`utilization(e,w) = allocated / net` when `net > 0`; undefined when `net = 0`.

### BR-UTL-002 — Utilization risk bands
| Band | Condition |
|---|---|
| UNAVAILABLE | `net = 0` and `allocated = 0` |
| UNDER_UTILIZED | `utilization < under_utilized_below (0.50)` |
| HEALTHY | `0.50 ≤ utilization < healthy_below (0.85)` |
| HIGH | `0.85 ≤ utilization ≤ 1.00` |
| OVERALLOCATED | `utilization > 1.00`, or `net = 0` and `allocated > 0` |

### BR-UTL-003 — Aggregate utilization is hours-weighted, not an average of ratios
`utilization(group) = Σ allocated / Σ net` over the employee-weeks in the group. The dashboard's
"average utilization" uses this formula.

### BR-UTL-004 — Allocation exceeds availability (overallocation finding)
Raise finding `ALLOCATION_EXCEEDS_AVAILABILITY` for an employee-week when
`allocated > net + tolerance_hours`. Severity HIGH if `allocated − net ≥ high_severity_excess_hours (8)`,
else MEDIUM. **Evaluation unit:** employee-week.

### BR-UTL-005 — Excess capacity (bench) after consecutive under-utilized weeks
An employee in band UNDER_UTILIZED (or with net > 0 and allocated = 0) for at least
`min_consecutive_weeks (2)` consecutive weeks is reported as excess capacity.

## ALC — Allocation

### BR-ALC-001 — Allocation field and date validity
`start_date ≤ end_date`; `0 < hours_per_week ≤ max_hours_per_week (60)`; the range lies within the
employee's employment dates. A range outside the project's dates is a validation warning.

### BR-ALC-002 — Allocation lifecycle transitions
`PROPOSED → CONFIRMED | CANCELLED`; `CONFIRMED → COMPLETED | CANCELLED`. COMPLETED and CANCELLED
are terminal.

### BR-ALC-003 — Overlapping allocation conflict with an exclusive (DEDICATED) assignment
Two counted allocations of the same employee whose date ranges overlap are a **conflict** when at
least one has `allocation_type` in `exclusive_allocation_types` (DEDICATED). Hours are irrelevant
(that is BR-UTL-004). Raise finding `OVERLAPPING_ALLOCATION_CONFLICT`.
**Evaluation unit:** unordered allocation pair (`ALLOC-a|ALLOC-b`, sorted).

### BR-ALC-004 — Allocation-to-demand reconciliation per project, role and week
`ratio = allocated(project, role, w) / counted demand(project, role, w)`:
UNDERSTAFFED `< balanced_lower (0.90)`; BALANCED `0.90–1.10`; OVERSTAFFED `> balanced_upper (1.10)`;
UNPLANNED when demand = 0 and allocated > 0.

### BR-ALC-005 — API write-path guard for new or changed allocations
Creating or changing an allocation through the API is rejected with **HTTP 409** if it would
cause BR-UTL-004 (`reject_overallocation`) or BR-ALC-003 (`reject_conflict`) in any week, unless
the request carries `override_reason` (`allow_override_with_reason`), which is stored in the audit
event. Bulk seed/import data is **not** guarded (A-17).

## SKL — Skills

### BR-SKL-001 — Proficiency scale 1–5
1 Awareness · 2 Beginner · 3 Practitioner · 4 Advanced · 5 Expert.

### BR-SKL-002 — Effective skill status is derived from dates, not from the recorded flag
Evaluated on a date `t`, first match wins:
1. **EXPIRED** — `expiry_date` is set and `expiry_date < t`
2. **PENDING** — `recorded_status = PENDING_VERIFICATION`
3. **STALE** — `t − last_verified_date > freshness_days (730)`
4. **VALID** — otherwise

### BR-SKL-003 — Recorded skill status is informational and never drives eligibility
`recorded_status` (CURRENT / EXPIRED / PENDING_VERIFICATION) is kept as source data only. All
logic uses the derived status of BR-SKL-002.

### BR-SKL-004 — Expired skill recorded as current (finding)
For the **current version** of each employee skill: if `recorded_status = CURRENT` and the derived
status at the run's `as_of_date` is EXPIRED, raise `EXPIRED_SKILL_TREATED_AS_CURRENT`.
**Evaluation unit:** `employee_skill_id`.

### BR-SKL-005 — Certification skills must carry an expiry date after verification
If `skill.requires_certification` then `expiry_date` is required and `expiry_date > last_verified_date`.
The generator sets `expiry_date = last_verified_date + validity_months`.

### BR-SKL-006 — Eligibility of an employee for a demand line
Employee `e` is eligible for demand line `L` in week `w` when **all** hold:
1. `e` is active in `w` (BR-EMP-002);
2. `role_family(e.role) = role_family(L.role)` (`require_same_role_family`);
3. `e` holds `L`'s PRIMARY skill with `proficiency ≥ min_proficiency` (default
   `default_min_proficiency = 3`);
4. that skill's derived status on the week's Monday (`evaluate_on = WEEK_START`) is in
   `eligible_statuses` (VALID).

### BR-SKL-007 — Deterministic match score and candidate ordering
`score = weight_exact_role (50) × [e.role = L.role] + weight_per_level_above_min (10) × (proficiency − min)
+ weight_per_secondary_skill (5) × (# SECONDARY skills of L that e holds VALID at ≥ their minimum)`.
Candidates are ordered by score descending, then `employee_id` ascending.

### BR-SKL-008 — Employee skill history is versioned (one current version per employee and skill)
A new assessment inserts a new row and closes the previous one
(`previous.effective_to = new.effective_from − 1 day`). At most one row per (employee, skill) has
`effective_to IS NULL`.

## DEM — Demand

### BR-DEM-001 — Demand line structure: one PRIMARY skill, bounded hours
Each line has exactly one PRIMARY requirement and at most `max_secondary_skills (2)` SECONDARY
requirements; `required_hours > 0`; `headcount ≥ 1`;
`required_hours ≤ headcount × standard_weekly_hours`.

### BR-DEM-002 — Demand line lifecycle transitions
`DRAFT → SUBMITTED | CANCELLED`; `SUBMITTED → APPROVED | REJECTED | CANCELLED`;
`APPROVED → CANCELLED`. REJECTED and CANCELLED are terminal. A line's week never changes —
to move demand, cancel the line and create a new one.

### BR-DEM-003 — Which demand lines count towards analysis
Lines with status in `counted_demand_statuses` (SUBMITTED, APPROVED) whose project status is in
`counted_project_statuses` (APPROVED, ACTIVE) and whose week lies within the project's dates.

### BR-DEM-004 — Duplicate project demand detection and exclusion
Lines sharing the `duplicate_key` (project, week, role, primary skill, min proficiency) are
duplicates. The line with the lowest line number is kept (`keep = LOWEST_LINE_NO`); every other
line raises `DUPLICATE_DEMAND` and, with `exclude_duplicates_from_analysis`, is excluded from
forecast and gap totals. **Evaluation unit:** the duplicate `demand_id`.

### BR-DEM-005 — Deterministic demand line numbering
`demand_id = DEM-<project_id>-<ISO year>W<ISO week, 2 digits>-<line_no, 2 digits>`; `line_no` is
1-based per project-week, at most `max_lines_per_project_week (99)`, assigned in creation order.

## TRN — Training

### BR-TRN-001 — Training lifecycle transitions
`PLANNED → IN_PROGRESS | CANCELLED`; `IN_PROGRESS → COMPLETED | CANCELLED`. COMPLETED requires
`completion_date`.

### BR-TRN-002 — Completed training creates a new employee skill version
On completion, a new `employee_skill` version is created (BR-SKL-008) with
`proficiency = target_proficiency`, `last_verified_date = completion_date`, and the training row
stores `outcome_employee_skill_id`.

## GAP — Coverage and skill gaps

### BR-GAP-001 — Deterministic processing order of demand lines
Counted, de-duplicated lines are processed by: `priority_rank`, `week_start_date`, `project_id`,
`line_no`.

### BR-GAP-002 — Committed coverage from existing allocations of eligible employees
For each (project, role, week), each employee's allocated hours on that project/role are applied to
the lines (in BR-GAP-001 order) for which the employee is eligible (BR-SKL-006), never more than a
line's remaining demand. `committed(L)` = hours applied to `L`.

### BR-GAP-003 — At-risk coverage from allocations of ineligible employees
Allocated hours on a project/role that could not be applied to any line because the employee is not
eligible (e.g. expired skill) are `at_risk(L)` for the line of matching role and primary skill
(or the first line of that role). They are **not** counted as coverage.

### BR-GAP-004 — Capacity ledger prevents double-counting an employee's hours
A ledger holds each employee-week's free hours (BR-CAP-009, never below 0). Every reallocation or
training recommendation **debits** the ledger; an hour can be used once across all projects.

### BR-GAP-005 — Gap hours and coverage ratio
`gap(L) = max(0, demand(L) − committed(L))`; `coverage_ratio = committed / demand`. Gap rows are
stored per run × project × role × primary skill × week.

### BR-GAP-006 — Gap severity bands
NONE when coverage ≥ 1; LOW ≥ `low_min_coverage (0.90)`; MEDIUM ≥ `medium_min_coverage (0.75)`;
HIGH ≥ `high_min_coverage (0.50)`; otherwise CRITICAL. Raised one level (max CRITICAL) for
projects with priority in `escalate_for_priorities`.

### BR-GAP-007 — Gap aggregation by role, skill, project and period
Stored rows are summed by any combination of role, primary skill, project, week and month
(BR-CAP-002). Hours are summed; ratios are recomputed from sums, never averaged.

### BR-GAP-008 — Excess capacity remaining after recommendations
After all strategies run, remaining ledger hours per employee-week are excess capacity, reported by
role and by primary skill held.

### BR-GAP-009 — Demand basis for gap analysis (planned or forecast)
`PLANNED` uses line hours. `FORECAST` scales each line by
`forecast(project, role, w) / planned(project, role, w)` from the selected forecast run.

### BR-GAP-010 — Default analysis window
From the week containing `as_of_date` to the end of the planning horizon, unless the request
specifies a window.

## REC — Recommendations

### BR-REC-001 — Recommendation strategies run as ordered passes over all gaps
Strategies implement one contract and run in `strategy_order` (REALLOCATE → TRAIN → HIRE). Each
pass walks all gaps in BR-GAP-001 order and may only reduce a gap's **residual** hours.

### BR-REC-002 — Reallocate free capacity of eligible employees
For each gap week, take eligible candidates (BR-SKL-006, order BR-SKL-007) with ledger hours
≥ `min_hours_per_week (4)` and debit `min(residual, ledger)`. Consecutive weeks for the same
employee/project/role are merged into one recommendation.

### BR-REC-003 — Train near-eligible employees when lead time allows
Candidates: active employees of the same role family who are not eligible, but either
(a) **RECERTIFY** — hold the primary skill at ≥ min proficiency with status EXPIRED, STALE or PENDING
(lead time `recertify_lead_weeks = 2`), or
(b) **UPSKILL** — hold it VALID at `min − max_levels_to_upskill` (lead time
`upskill_lead_weeks_per_level = 4` per level).
Feasible only if `as_of + lead time ≤ gap week` and the ledger has `training_hours_per_week (8)`
during the training weeks plus hours in the gap weeks. Ordered by lead time, then free hours
(desc), then `employee_id`. At most `max_trainings_per_employee_per_run (1)`.

### BR-REC-004 — Hire for sustained residual gaps
Group residual gaps by (role, primary skill). Recommend HIRE when the group has residual hours in
≥ `min_gap_weeks (3)` weeks and the average weekly residual over those weeks is ≥
`min_avg_weekly_gap_hours (20)`. `headcount = max(1, ceil(avg / 40 − headcount_rounding_tolerance_fte (0.2)))`.
`hire_type = PERMANENT` if the hours-weighted remaining duration of the driving projects (from the
first gap week to project end) is ≥ `permanent_min_remaining_project_weeks (26)`, else CONTRACT.
Residual hours below the thresholds remain **unresolved** and are reported.

### BR-REC-005 — Every recommendation is explainable and traceable
Each recommendation stores: `rule_ids`, a human-readable `explanation`, `assumptions`
(parameter values used), `source_refs` (demand, employee, skill, project IDs), linked gap rows, the
run ID, rules version and rules-file hash.

### BR-REC-006 — Recommendation lifecycle transitions
`PROPOSED → ACCEPTED | REJECTED`; `ACCEPTED → IMPLEMENTED`. Implementing a TRAIN recommendation
creates a `training` row referencing it.

## FCT — Forecasting

### BR-FCT-001 — Planned, forecast and actual demand are distinct, separately stored quantities
Planned = `demand_plan`; forecast = `forecast_result` (per run and method); actual = `demand_actual`.

### BR-FCT-002 — Forecast grain is project × role × ISO week, with deterministic roll-ups
Roll-up to role, project, period by summation; to skill by allocating each project-role-week forecast
to primary skills in proportion to that week's planned hours per primary skill.

### BR-FCT-003 — Deterministic baseline forecasting methods
- **NAIVE_PLAN:** `forecast(w) = planned(w)`.
- **MOVING_AVERAGE:** `forecast(w) = mean(actual)` of the last `moving_average_window_weeks (4)`
  weeks before the origin (flat for all future weeks).
- **PLAN_RATIO (default):** `r = Σ actual / Σ planned` over the last `plan_ratio_window_weeks (4)`
  weeks before the origin for the project-role; if `Σ planned < plan_ratio_min_planned_hours (8)`
  fall back to the role-level ratio, then the global ratio, then 1.0;
  `r` is clipped to [`plan_ratio_min (0.5)`, `plan_ratio_max (1.5)`]; `forecast(w) = planned(w) × r`.

### BR-FCT-004 — No look-ahead: forecasts only read actuals before the forecast origin
The forecast origin is `as_of_date`. The actuals repository used by forecast methods only accepts
queries with `week_start_date < origin`. Hold-out actuals are read only by the evaluator.

### BR-FCT-005 — Forecast accuracy metrics on held-out actuals
`MAE = mean|F − A|`; `WAPE = Σ|F − A| / Σ A`; `BIAS = Σ(F − A) / Σ A`; reported per method at
`PROJECT_ROLE_WEEK` and `ROLE_WEEK` levels over the hold-out weeks.

## VAL — Data validation checks

### BR-VAL-001 — Primary keys are unique and match their ID pattern
### BR-VAL-002 — Every foreign key resolves to an existing record
### BR-VAL-003 — Every enum column holds an allowed value
### BR-VAL-004 — Date ranges are ordered (start ≤ end) and inside their parent ranges
### BR-VAL-005 — Capacity reconciliation identity holds for every employee-week
### BR-VAL-006 — Recorded lifecycle histories only use allowed transitions
### BR-VAL-007 — IDs are deterministic and immutable
### BR-VAL-008 — Every recommendation references existing rules, gaps and source records
### BR-VAL-009 — Work schedules do not overlap and cover every employed day

These checks run on generated files (Phase 3) and on the database (Phase 7) and appear in the
validation report.

---

## Anomaly → rule map (used by detection and evaluation)

| Anomaly type | Detecting rule | Evaluation unit |
|---|---|---|
| ALLOCATION_EXCEEDS_AVAILABILITY | BR-UTL-004 | employee-week |
| EXPIRED_SKILL_TREATED_AS_CURRENT | BR-SKL-004 | employee_skill_id |
| DUPLICATE_DEMAND | BR-DEM-004 | duplicate demand_id |
| OVERLAPPING_ALLOCATION_CONFLICT | BR-ALC-003 | allocation pair |

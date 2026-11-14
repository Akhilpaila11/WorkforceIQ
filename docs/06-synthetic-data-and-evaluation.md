# 06 — Synthetic Data, Ground Truth and Evaluation Design

Phase 3 implements this design. Parameters live in
[`generator.starter.toml`](../backend/config/generator.starter.toml) and
[`generator.full.toml`](../backend/config/generator.full.toml).

## 1. Modes

| | Starter | Full |
|---|---|---|
| Employees | 100 | 5,000 |
| Skills | 30 | 300 |
| Projects | 10 | 500 |
| Roles | 10 | 24 |
| Demand horizon | 13 weeks (2026-W01 → W13) | 52 weeks (2026-W01 → W52) |
| Forecast hold-out | 4 weeks (W10 → W13) | 13 weeks (W40 → W52) |
| `as_of_date` | 2026-03-02 | 2026-09-28 |
| Seed | 20261022 | 20261022 |

## 2. Generation order (master data first)

1. roles → 2. skills → 3. role_skill → 4. employees → 5. work schedules → 6. employee skills
(with history versions) → 7. projects → 8. demand lines + skill requirements → 9. leave →
10. allocations → 11. training → 12. actuals (from the **clean** baseline) →
13. **baseline self-check** → 14. anomaly injection → 15. ground truth → 16. export + manifest.

## 3. Realistic distributions (inputs, not outcomes)

| Aspect | Rule of thumb (configurable) |
|---|---|
| Roles | Weighted mix: engineering-heavy (≈45 % engineering roles, 15 % data, 10 % QA, 10 % cloud/infra, rest design/product/delivery/security) |
| Seniority | JUNIOR 20 %, MID 35 %, SENIOR 28 %, LEAD 12 %, PRINCIPAL 5 % |
| Skills per employee | uniform 3–8 (starter) / 3–10 (full); core skills of the role more likely |
| Proficiency | levels 1–5 weighted 10/20/35/25/10 %, nudged up for senior employees |
| Verification dates | spread over the 1,095 days before `as_of` ⇒ about one third STALE (> 730 days) |
| Certification skills | 20 % of skills; validity 12/24/36 months ⇒ some certificates genuinely expired (and correctly recorded as EXPIRED) |
| Part-time | 12 % of employees at 20/24/30/32 h; a few schedule changes mid-horizon |
| Leave | ≈20 annual-leave days/year in 1–10 day blocks; sick leave episodes Poisson(1.5/year) |
| Projects | priority 10/30/40/20 % (CRITICAL/HIGH/MEDIUM/LOW); ramp-up → plateau → ramp-down demand curve; 2–5 (starter) / 2–8 (full) roles per project |
| Demand volume | total planned hours ≈ 0.90 × total net capacity, unevenly spread so some roles/skills are scarce (gaps) and others are in surplus (bench) |
| Allocations | mean utilization ≈ 78 %; ≈10 % bench; ≈15 % DEDICATED |
| Training history | completed and in-progress courses that created skill versions (BR-TRN-002) |

**Outcome labels are never sampled.** Utilization bands, skill statuses, gaps and
recommendations are *computed* from these inputs by the business rules (A-22).

## 4. Baseline invariants (clean data before injection)

The generator constructs the baseline so that, before injection:

- every employee-week satisfies `allocated ≤ net` (leave is placed around allocations or allocations
  are split around leave);
- no allocation overlaps a DEDICATED allocation of the same employee;
- every (project, week, role, primary skill, min proficiency) key is unique;
- every current employee-skill row's `recorded_status` agrees with its derived status at `as_of`.

Step 13 verifies these with **independent** checks in `datagen/validation` (they do not import
the backend's detection engine, so a bug in one cannot hide a bug in the other).

## 5. Synthetic actuals (not a copy of the plan)

Per (project, role, week), from the clean plan:

```
actual = planned × project_realization × weekly_noise × scope_factor(w)
project_realization ~ Normal(0.95, 0.08)      (one draw per project)
weekly_noise        ~ Normal(1.00, 0.10)      (one draw per project-role-week)
scope_factor(w)     = 1, or a step up to ×1.10–1.30 from a random week (15 % of projects)
cancellation        : 5 % of projects stop producing actuals from a random week (plan continues)
unplanned work      : 3 % chance of actual hours in a week with no planned demand
```

Results are clipped at 0 and rounded to 0.5 h.

## 6. Anomaly injection

Counts in the config are **injection events**; one event can create several ground-truth rows
(one per evaluation unit). Each anomaly type targets distinct employees/lines so labels stay
separable.

| Type | Injection method(s) | GT unit |
|---|---|---|
| ALLOCATION_EXCEEDS_AVAILABILITY | (a) approve leave over weeks where the employee is heavily allocated; (b) raise `hours_per_week` of a SHARED allocation above net; (c) allocate a part-timer beyond their schedule | each affected employee-week |
| EXPIRED_SKILL_TREATED_AS_CURRENT | set `expiry_date` of a current certification skill to 1–180 days before `as_of` while leaving `recorded_status = CURRENT` | employee_skill_id |
| DUPLICATE_DEMAND | copy a demand line (and its skill requirements) to the next line number in the same project-week; exact copy or hours × 0.9–1.1 | duplicate demand_id |
| OVERLAPPING_ALLOCATION_CONFLICT | add a SHARED allocation on another project overlapping an existing DEDICATED one, with hours that still fit capacity | allocation pair |

Anomalous records stay in the normal input files (CSV/JSON/SQL), indistinguishable from other rows.

## 7. Ground-truth files

Written to a separate folder; never loaded into the application database; read only by the
evaluator.

| Column | Example |
|---|---|
| gt_id | GT-000001 |
| anomaly_type | ALLOCATION_EXCEEDS_AVAILABILITY |
| rule_id | BR-UTL-004 |
| evaluation_unit | EMPLOYEE_WEEK |
| evaluation_key | EMP-000042\|2026-03-09 |
| primary_record_type / primary_record_id | allocation / ALLOC-2026-000117 |
| source_record_ids | ALLOC-2026-000117\|AVL-2026-000390 |
| week_start_date | 2026-03-09 |
| injection_method | LEAVE_AFTER_STAFFING |
| expected_outcome | "Finding ALLOCATION_EXCEEDS_AVAILABILITY for EMP-000042 in 2026-W11: allocated 40.00 h > net 16.00 h" |

## 8. Detection evaluation

Per anomaly type, findings and ground truth are compared on the evaluation key:
TP = in both; FP = finding only; FN = ground truth only; TN = population − TP − FP − FN, where the
population is: active employee-weeks (overallocation), current employee-skill rows (expired),
counted demand lines (duplicates), overlapping same-employee allocation pairs (conflicts).
Reported: precision, recall, F1 per type and micro-averaged, plus confusion-matrix counts.

## 9. Output layout and reproducibility

```
data/generated/<mode>/
  csv/<table>.csv          one file per table, sorted by primary key
  json/<table>.json        same rows, same order
  sql/seed.sql             INSERTs in foreign-key order, one transaction
  ground_truth/ground_truth.csv
  ground_truth/ground_truth.json
  manifest.json            per file: row count, SHA-256; config + seed + generator version
```

Determinism rules: one `random.Random` per generation stage, seeded from
`SHA-256(f"{seed}:{stage}")` (changing one stage does not shift others); no clock reads; explicit
sorting everywhere; `Decimal` hours with fixed formatting; UTF-8, LF line endings; JSON with sorted
keys. Reproducibility check: generate twice into separate folders and compare row counts and
SHA-256 of every file (guaranteed for the same Python minor version).

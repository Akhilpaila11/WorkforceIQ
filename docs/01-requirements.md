# 01 — Requirements

**Project:** WorkforceIQ — Intelligent Workforce Demand Forecasting and Skill Gap Analysis System
**Status:** Phase 1 (design) — approved scope for Phases 2–7

---

## 1. Business problem (plain language)

A services organisation sells projects. Each project needs people with specific **roles** and
**skills** for specific **weeks**. The organisation has a limited pool of **employees**, whose
**capacity** is reduced by part-time contracts, leave, training and existing project
**allocations**.

WorkforceIQ answers, for every week of the planning horizon:

1. How much work (hours) is required, by role, skill and project?
2. Who can do it — which employees have a *valid* skill at the required level and free hours?
3. Where are the **gaps** (not enough qualified hours) and where is **excess capacity**?
4. What should we do about each gap — **reallocate** someone, **train** someone, or **hire** —
   and *why*?
5. Which records look wrong (over-allocations, expired skills treated as current, duplicate
   demand, conflicting assignments)?
6. How accurate are our forecasts and exception detection, measured against known truth?

## 2. Users

| Persona | Main questions |
|---|---|
| Resource manager | Who is free? Who is overallocated? Where do I reallocate? |
| Project / delivery manager | Is my project's demand covered? Which lines are at risk? |
| HR / Learning & Development | Which skills are expiring? Whom should we train, in what? |
| Leadership | How many people should we hire, for which roles, and how sure are we? |
| Data / audit reviewer | Why was this recommendation made? What changed and when? |

## 3. Functional requirements

| ID | Requirement | Phase |
|---|---|---|
| FR-01 | Manage employees, roles, skills and employee skill profiles (CRUD with history) | 2, 4 |
| FR-02 | Manage projects and weekly demand plans with skill requirements | 2, 4 |
| FR-03 | Manage allocations, work schedules (part-time) and leave | 2, 4 |
| FR-04 | Manage training activities and link them to recommendations | 2, 4 |
| FR-05 | Generate reproducible synthetic data (starter and full modes, seed 20261022) | 3 |
| FR-06 | Inject labelled anomalies; export ground truth separately from input data | 3 |
| FR-07 | Export CSV, JSON and SQL seed data with a checksum manifest | 3 |
| FR-08 | Calculate weekly capacity, utilization and risk bands per employee | 5 |
| FR-09 | Match demand to eligible supply without double-counting capacity | 5 |
| FR-10 | Compute skill gaps by role, skill, project and period; compute excess capacity | 5 |
| FR-11 | Produce explainable REALLOCATE / TRAIN / HIRE recommendations (strategy pattern) | 5 |
| FR-12 | Detect the four anomaly types and store findings | 5 |
| FR-13 | Forecast demand with deterministic baselines; evaluate on held-out actuals | 5 |
| FR-14 | Evaluate anomaly detection (precision, recall, F1, confusion matrix) | 5, 7 |
| FR-15 | Versioned REST API under `/api/v1` with pagination, filtering, consistent errors | 4 |
| FR-16 | React dashboard with the ten required pages, using live API data only | 6 |
| FR-17 | Immutable audit history for every change to business records | 2, 4 |
| FR-18 | Reports: validation, reproducibility, forecast accuracy, detection accuracy | 7 |

## 4. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-01 | Strict 3-tier architecture; modular monolith; SOLID applied and documented |
| NFR-02 | Deterministic: same seed + config + code ⇒ byte-identical generated files |
| NFR-03 | No hard-coded credentials; all configuration via environment variables / config files |
| NFR-04 | Type hints throughout the backend; `mypy --strict` and `ruff` clean |
| NFR-05 | Full-mode analysis (5,000 employees × 52 weeks) completes in minutes on a laptop |
| NFR-06 | Every recommendation and finding is traceable to rule IDs and source record IDs |
| NFR-07 | Runs on Windows 11 with PowerShell; no Docker required |
| NFR-08 | Fully synthetic data; no personal data; provenance documented |
| NFR-09 | No feature is reported as working unless executed or tested |

## 5. Out of scope (explicit)

- Authentication / authorisation (an `X-Actor` header is recorded in audit events instead).
- Machine-learning forecasting (only deterministic baselines; no ML claims are made).
- Costs, budgets, rates and financial optimisation.
- Public-holiday calendars and multi-country working-time rules.
- Overtime contracts (max scheduled hours = 40 h/week).
- Microservices, message queues, Docker/Kubernetes deployment.

## 6. Definition of done (for the final submission)

- `pytest` passes (unit + integration), `ruff` and `mypy` are clean.
- The generator runs twice with identical row counts and SHA-256 checksums.
- Detection metrics and forecast metrics are produced by code, not typed by hand.
- The frontend shows only API-provided values.
- All artifacts listed in the brief exist and are linked from the README.

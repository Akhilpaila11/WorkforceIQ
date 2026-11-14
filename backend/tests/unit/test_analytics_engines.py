"""Analysis engines on small hand-built inputs (no database).

Week of 2026-03-02 (Mon) .. 2026-03-08 is "W1"; the horizon is 4 weeks from 2026-02-23.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.domain.enums import (
    AnomalyType,
    EffectiveSkillStatus,
    ForecastMethod,
    GapSeverity,
    RecommendationType,
    RiskBand,
)
from app.domain.rules_config import load_rules
from app.modules.analytics.capacity import CapacityCalculator, prorated_weeks, risk_band
from app.modules.analytics.detection import Finding
from app.modules.analytics.evaluation import evaluate_detection
from app.modules.analytics.forecasting import ForecastEvaluator
from app.modules.analytics.gaps import gap_severity
from app.modules.analytics.inputs import (
    ActualIn,
    AllocationIn,
    AnalysisContext,
    AnalysisInputs,
    AvailabilityIn,
    DemandLineIn,
    EmployeeIn,
    ProjectIn,
    Requirement,
    RoleIn,
    SkillIn,
    SkillVersionIn,
    TrainingIn,
)
from app.modules.analytics.pipeline import AnalysisPipeline
from app.modules.analytics.skills import SkillStatusEvaluator

RULES = load_rules(Path(__file__).resolve().parents[2] / "config" / "business_rules.toml")
W0 = date(2026, 2, 23)  # first horizon week (history)
W1 = date(2026, 3, 2)  # as-of week = forecast origin
W2, W3 = W1 + timedelta(weeks=1), W1 + timedelta(weeks=2)
WEEKDAYS = frozenset({1, 2, 3, 4, 5})


def ctx(**kw) -> AnalysisContext:
    return AnalysisContext(
        as_of=kw.pop("as_of", W1),
        horizon_start=W0,
        horizon_end=W3 + timedelta(days=6),
        rules=RULES,
        **kw,
    )


ROLES = (RoleIn("ROL-000001", "BACKEND", "ENGINEERING"), RoleIn("ROL-000002", "UX", "DESIGN"))
SKILLS = (SkillIn("SKL-000001", "PYTHON", False), SkillIn("SKL-000002", "AWS", True))


def emp(n: int, role: str = "ROL-000001", hire: date = date(2020, 1, 1), term=None) -> EmployeeIn:
    return EmployeeIn(f"EMP-{n:06d}", role, hire, term)


def schedule(n: int, hours: float = 40.0, start: date = date(2020, 1, 1)) -> AvailabilityIn:
    return AvailabilityIn(
        f"AVL-2026-{n:06d}", f"EMP-{n:06d}", "WORK_SCHEDULE", start, None, hours, None, "ACTIVE"
    )


def leave(n: int, emp_n: int, start: date, end: date, hpd=None, status="APPROVED"):
    return AvailabilityIn(
        f"AVL-2026-{n:06d}", f"EMP-{emp_n:06d}", "ANNUAL_LEAVE", start, end, None, hpd, status
    )


def skill(n: int, emp_n: int, level: int = 4, verified: date = date(2025, 6, 1), **kw):
    return SkillVersionIn(
        employee_skill_id=f"ESK-{n:06d}",
        employee_id=f"EMP-{emp_n:06d}",
        skill_id=kw.get("skill_id", "SKL-000001"),
        proficiency_level=level,
        last_verified_date=verified,
        expiry_date=kw.get("expiry"),
        recorded_status=kw.get("recorded", "CURRENT"),
        effective_from=kw.get("effective_from", date(2020, 1, 1)),
        effective_to=kw.get("effective_to"),
    )


def alloc(n: int, emp_n: int, start: date, end: date, hours: float, **kw) -> AllocationIn:
    return AllocationIn(
        f"ALLOC-2026-{n:06d}",
        f"EMP-{emp_n:06d}",
        kw.get("project", "PRJ-2026-000001"),
        kw.get("role", "ROL-000001"),
        start,
        end,
        hours,
        kw.get("kind", "SHARED"),
        kw.get("status", "CONFIRMED"),
    )


def line(week: date, line_no: int, hours: float, **kw) -> DemandLineIn:
    project = kw.get("project", "PRJ-2026-000001")
    iso = week.isocalendar()
    return DemandLineIn(
        demand_id=f"DEM-{project}-{iso.year}W{iso.week:02d}-{line_no:02d}",
        project_id=project,
        role_id=kw.get("role", "ROL-000001"),
        week_start_date=week,
        line_no=line_no,
        required_hours=hours,
        status=kw.get("status", "APPROVED"),
        primary=Requirement(kw.get("skill", "SKL-000001"), kw.get("min_prof", 3)),
    )


PROJECT = ProjectIn("PRJ-2026-000001", "MEDIUM", "ACTIVE", date(2026, 1, 1), date(2026, 12, 31))


def inputs(**kw) -> AnalysisInputs:
    return AnalysisInputs(roles=ROLES, skills=SKILLS, projects=(PROJECT,), **kw)


def capacity_of(data: AnalysisInputs, n: int = 1):
    return CapacityCalculator(ctx()).all(data)[f"EMP-{n:06d}"]


# ------------------------------------------------------------------ capacity, FTE, part time, leave
def test_full_time_week_and_fte_arithmetic():
    cap = capacity_of(inputs(employees=(emp(1),), availability=(schedule(1),)))
    assert list(cap.gross) == [40.0] * 4 and list(cap.net) == [40.0] * 4
    assert not cap.part_time.any()
    assert cap.gross.sum() / (40 * 4) == 1.0  # BR-CAP-001: 160 h over 4 weeks = 1 FTE


def test_part_time_schedule_and_midweek_hire():
    data = inputs(
        employees=(emp(1), emp(2, hire=W1 + timedelta(days=2))),  # second hired on Wednesday
        availability=(schedule(1, 20.0), schedule(2, 40.0, start=W1 + timedelta(days=2))),
    )
    caps = CapacityCalculator(ctx()).all(data)
    assert list(caps["EMP-000001"].gross) == [20.0] * 4
    assert caps["EMP-000001"].part_time.all()
    assert list(caps["EMP-000002"].gross) == [0.0, 24.0, 40.0, 40.0]  # 3 of 5 days in W1
    assert list(caps["EMP-000002"].active) == [False, True, True, True]  # BR-EMP-002


def test_leave_caps_and_net_identity():
    data = inputs(
        employees=(emp(1),),
        availability=(
            schedule(1),
            leave(2, 1, W1, W1 + timedelta(days=1)),  # 2 full days
            leave(3, 1, W1, W1, hpd=4.0),  # overlaps day 1: never deducted twice
            leave(4, 1, W2, W2, hpd=4.0),  # half day
            leave(5, 1, W3, W3 + timedelta(days=6), status="REQUESTED"),  # not approved
            leave(6, 1, W0 + timedelta(days=5), W0 + timedelta(days=6)),  # weekend only
        ),
        trainings=(
            TrainingIn(
                "TRN-2026-000001",
                "EMP-000001",
                "SKL-000001",
                W1,
                W2 + timedelta(days=4),
                10.0,
                "PLANNED",
            ),
        ),
    )
    cap = capacity_of(data)
    assert list(cap.leave) == [0.0, 16.0, 4.0, 0.0]
    assert list(cap.training) == [0.0, 6.0, 10.0, 0.0]  # 2 h/day on the 3 days not on leave
    assert list(cap.net) == [40.0, 18.0, 26.0, 40.0]
    assert (cap.gross - cap.leave - cap.training - cap.net == 0).all()


def test_allocations_are_prorated_and_not_reduced_by_leave():
    data = inputs(
        employees=(emp(1),),
        availability=(schedule(1), leave(2, 1, W1, W1 + timedelta(days=4))),
        allocations=(
            alloc(1, 1, W0 + timedelta(days=2), W1 + timedelta(days=6), 20.0),  # Wed W0..W1
            alloc(2, 1, W2, W3, 10.0, status="PROPOSED"),  # not counted (BR-CAP-008)
        ),
    )
    cap = capacity_of(data)
    assert list(cap.allocated) == [12.0, 20.0, 0.0, 0.0]
    assert cap.free[1] == -20.0  # on leave all week but still allocated
    assert prorated_weeks(
        40.0, W1 + timedelta(days=4), W1 + timedelta(days=11), [W1, W2], WEEKDAYS
    ) == {
        W1: 8.0,
        W2: 40.0,
    }


@pytest.mark.parametrize(
    ("net", "allocated", "band"),
    [
        (40, 0, RiskBand.UNDER_UTILIZED),
        (40, 19.99, RiskBand.UNDER_UTILIZED),
        (40, 20, RiskBand.HEALTHY),
        (40, 34, RiskBand.HIGH),
        (40, 40, RiskBand.HIGH),
        (40, 40.5, RiskBand.OVERALLOCATED),
        (0, 0, RiskBand.UNAVAILABLE),
        (0, 1, RiskBand.OVERALLOCATED),
    ],
)
def test_utilization_band_boundaries(net, allocated, band):
    assert risk_band(net, allocated, 0.50, 0.85) is band


# ------------------------------------------------------------------ skills and eligibility
def test_skill_status_boundaries():
    status = SkillStatusEvaluator(730)
    on = date(2026, 3, 2)
    assert status.status(skill(1, 1, expiry=on), on) is EffectiveSkillStatus.VALID  # expires today
    assert (
        status.status(skill(1, 1, expiry=on - timedelta(days=1)), on)
        is EffectiveSkillStatus.EXPIRED
    )
    assert (
        status.status(skill(1, 1, recorded="PENDING_VERIFICATION"), on)
        is EffectiveSkillStatus.PENDING
    )
    assert (
        status.status(skill(1, 1, verified=on - timedelta(days=730)), on)
        is EffectiveSkillStatus.VALID
    )
    assert (
        status.status(skill(1, 1, verified=on - timedelta(days=731)), on)
        is EffectiveSkillStatus.STALE
    )
    # recorded EXPIRED is informational only (BR-SKL-003): dates decide
    assert status.status(skill(1, 1, recorded="EXPIRED"), on) is EffectiveSkillStatus.VALID


def _gap_case(**skill_kw):
    """One demand line (40 h, min level 3) staffed by EMP-000001 for 40 h."""
    data = inputs(
        employees=(emp(1, role=skill_kw.pop("role", "ROL-000001")),),
        availability=(schedule(1),),
        skill_versions=(skill(1, 1, **skill_kw),),
        demand=(line(W1, 1, 40.0),),
        allocations=(alloc(1, 1, W1, W1 + timedelta(days=6), 40.0, role="ROL-000001"),),
    )
    result = AnalysisPipeline(ctx(), data).run()
    (row,) = result.gaps.rows
    return row


def test_eligible_employee_commits_coverage():
    row = _gap_case(level=3)
    assert (row.demand_hours, row.committed_hours, row.at_risk_hours) == (40.0, 40.0, 0.0)
    assert row.coverage_ratio == 1.0


@pytest.mark.parametrize(
    "skill_kw",
    [
        {"level": 2},  # below min proficiency
        {"expiry": W1 - timedelta(days=1)},  # expired before the week starts
        {"verified": W1 - timedelta(days=731)},  # stale
        {"recorded": "PENDING_VERIFICATION"},
        {"role": "ROL-000002"},  # other role family
        {"effective_from": W1 + timedelta(days=1)},  # skill acquired after the week's Monday
    ],
)
def test_ineligible_allocations_are_at_risk_not_coverage(skill_kw):
    row = _gap_case(**skill_kw)
    assert row.committed_hours == 0.0 and row.at_risk_hours == 40.0 and row.gap_hours == 40.0


# ------------------------------------------------------------------ gaps, ledger, double counting
def test_free_capacity_is_never_offered_twice():
    """Two projects need 30 h each in W1; the only eligible employee has 40 h free."""
    second = ProjectIn("PRJ-2026-000002", "HIGH", "ACTIVE", date(2026, 1, 1), date(2026, 12, 31))
    data = AnalysisInputs(
        roles=ROLES,
        skills=SKILLS,
        projects=(PROJECT, second),
        employees=(emp(1),),
        availability=(schedule(1),),
        skill_versions=(skill(1, 1),),
        demand=(line(W1, 1, 30.0), line(W1, 1, 30.0, project="PRJ-2026-000002")),
    )
    result = AnalysisPipeline(ctx(), data).run()
    w1 = [g for g in result.gaps.rows if g.week_start_date == W1]
    assert [g.project_id for g in w1] == ["PRJ-2026-000002", "PRJ-2026-000001"]  # HIGH first
    assert [g.reallocated_hours for g in w1] == [30.0, 10.0]
    reallocate = [
        r
        for r in result.recommendations
        if r.recommendation_type is RecommendationType.REALLOCATE and r.period_start == W1
    ]
    assert sum(r.hours for r in reallocate) == 40.0  # exactly the free hours, not 60
    assert result.recommendations and all(
        abs(sum(r.links.values()) - r.hours) < 1e-9 for r in result.recommendations
    )


def test_overallocated_employee_commits_only_net_hours():
    data = inputs(
        employees=(emp(1),),
        availability=(schedule(1), leave(2, 1, W1, W1 + timedelta(days=1))),  # net 24 h
        skill_versions=(skill(1, 1),),
        demand=(line(W1, 1, 40.0),),
        allocations=(alloc(1, 1, W1, W1 + timedelta(days=6), 40.0),),
    )
    row = next(g for g in AnalysisPipeline(ctx(), data).run().gaps.rows if g.week_start_date == W1)
    assert (row.committed_hours, row.at_risk_hours, row.gap_hours) == (24.0, 16.0, 16.0)


def test_gap_severity_bands_and_escalation():
    bands = {"low": 0.9, "medium": 0.75, "high": 0.5}
    esc = frozenset({"CRITICAL"})
    assert gap_severity(1.0, "CRITICAL", bands, esc) is GapSeverity.NONE
    assert gap_severity(0.9, "LOW", bands, esc) is GapSeverity.LOW
    assert gap_severity(0.75, "LOW", bands, esc) is GapSeverity.MEDIUM
    assert gap_severity(0.5, "LOW", bands, esc) is GapSeverity.HIGH
    assert gap_severity(0.49, "LOW", bands, esc) is GapSeverity.CRITICAL
    assert gap_severity(0.9, "CRITICAL", bands, esc) is GapSeverity.MEDIUM


# ------------------------------------------------------------------ recommendations
def _hire_case(weeks: list[date], hours: float):
    data = inputs(demand=tuple(line(w, 1, hours) for w in weeks))
    return AnalysisPipeline(ctx(), data).run()


def test_hire_needs_three_weeks_and_twenty_hours_on_average():
    assert not _hire_case([W1, W2], 60.0).recommendations  # only 2 weeks: unresolved
    assert not _hire_case([W1, W2, W3], 19.5).recommendations  # below 20 h/week
    result = _hire_case([W1, W2, W3], 60.0)
    (hire,) = result.recommendations
    assert hire.recommendation_type is RecommendationType.HIRE
    assert hire.headcount == 2  # max(1, ceil(60/40 - 0.2)) = 2
    assert hire.hours == 180.0 and hire.hire_type is not None
    assert {"BR-REC-004", "BR-REC-001"} <= set(hire.rule_ids)
    assert "Hire 2" in hire.explanation and hire.assumptions["avg_weekly_residual_hours"] == 60.0


def test_train_recertifies_a_stale_holder_when_lead_time_allows():
    data = inputs(
        employees=(emp(1),),
        availability=(schedule(1),),
        skill_versions=(skill(1, 1, level=4, verified=W1 - timedelta(days=800)),),  # STALE
        demand=(line(W3, 1, 20.0),),
    )
    result = AnalysisPipeline(ctx(), data).run()
    (train,) = result.recommendations
    assert train.recommendation_type is RecommendationType.TRAIN
    assert train.employee_id == "EMP-000001" and train.hours == 20.0
    assert (
        train.assumptions["training_kind"] == "RECERTIFY" and train.assumptions["lead_weeks"] == 2
    )
    refs = {(r["type"], r["id"]) for r in train.source_refs}
    assert {
        ("employee", "EMP-000001"),
        ("skill", "SKL-000001"),
        ("project", PROJECT.project_id),
    } <= refs
    # lead time 2 weeks from W1 -> not possible for a W2 need
    data_w2 = inputs(
        employees=data.employees,
        availability=data.availability,
        skill_versions=data.skill_versions,
        demand=(line(W2, 1, 20.0),),
    )
    assert not AnalysisPipeline(ctx(), data_w2).run().recommendations


# ------------------------------------------------------------------ forecasting
def _forecast(actuals: tuple[ActualIn, ...], planned: float = 100.0, history_planned=100.0):
    lines = [line(W0, 1, history_planned)] + [line(w, 1, planned) for w in (W1, W2, W3)]
    data = inputs(demand=tuple(lines), actuals=actuals)
    rows = AnalysisPipeline(ctx(), data).run().forecast.rows
    return {(r.method, r.week_start_date): r.forecast_hours for r in rows}


def actual(week: date, hours: float, role: str = "ROL-000001") -> ActualIn:
    return ActualIn("PRJ-2026-000001", role, week, hours)


def test_forecast_methods_arithmetic():
    f = _forecast((actual(W0, 80.0),))
    assert f[(ForecastMethod.NAIVE_PLAN, W2)] == 100.0
    assert f[(ForecastMethod.PLAN_RATIO, W2)] == pytest.approx(80.0)  # ratio 80/100
    # moving average over 4 weeks before the origin; only W0 is inside the horizon
    assert f[(ForecastMethod.MOVING_AVERAGE, W3)] == pytest.approx(80.0)


def test_plan_ratio_is_clipped_and_falls_back():
    assert _forecast((actual(W0, 300.0),))[(ForecastMethod.PLAN_RATIO, W1)] == 150.0  # max 1.5
    assert _forecast((actual(W0, 10.0),))[(ForecastMethod.PLAN_RATIO, W1)] == 50.0  # min 0.5
    # history plan below 8 h for the project-role, role and globally -> default ratio 1.0
    assert (
        _forecast((actual(W0, 6.0),), history_planned=4.0)[(ForecastMethod.PLAN_RATIO, W1)] == 100.0
    )


def test_no_look_ahead_actuals_at_or_after_origin_are_ignored():
    base = _forecast((actual(W0, 80.0),))
    leaked = _forecast((actual(W0, 80.0), actual(W1, 500.0), actual(W2, 1.0)))
    assert base == leaked


def test_forecast_error_metrics_and_unavailable_case():
    evaluator = ForecastEvaluator(
        [actual(W1, 100.0), actual(W2, 50.0, role="ROL-000002")], W1, (W1, W2)
    )
    forecasts = {"M": {("PRJ-2026-000001", "ROL-000001", W1): 110.0}}
    m = evaluator.evaluate(forecasts)["methods"]["M"]["PROJECT_ROLE_WEEK"]
    assert m["points"] == 2 and m["MAE"] == 30.0  # (10 + 50) / 2
    assert m["WAPE"] == 0.4 and m["BIAS"] == round(-40 / 150, 4)
    none = ForecastEvaluator([actual(W0, 100.0)], W1, (W1, W2)).evaluate(forecasts)
    assert none["available"] is False and "no actual demand" in none["reason"]


# ------------------------------------------------------------------ anomaly detection
def _findings(data: AnalysisInputs, **kw) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for f in AnalysisPipeline(ctx(**kw), data).run().detection.findings:
        found.setdefault(f.anomaly_type.value, set()).add(f.evaluation_key)
    return found


def test_allocation_exceeding_availability():
    data = inputs(
        employees=(emp(1), emp(2)),
        availability=(schedule(1), schedule(2, 20.0), leave(3, 1, W1, W1)),
        allocations=(
            alloc(1, 1, W1, W2 + timedelta(days=6), 40.0),  # W1: net 32 < 40
            alloc(2, 2, W1, W1 + timedelta(days=6), 20.0),  # part-timer exactly at capacity
            alloc(3, 2, W2, W2 + timedelta(days=6), 20.01),  # within the 0.01 h tolerance
        ),
    )
    found = _findings(data)
    assert found[AnomalyType.ALLOCATION_EXCEEDS_AVAILABILITY.value] == {f"EMP-000001|{W1}"}


def test_expired_skill_treated_as_current():
    data = inputs(
        employees=(emp(1),),
        skill_versions=(
            skill(1, 1, expiry=W1 - timedelta(days=1)),  # finding
            skill(2, 1, skill_id="SKL-000002", expiry=W1 - timedelta(days=1), recorded="EXPIRED"),
            skill(3, 1, skill_id="SKL-000002", expiry=W1 - timedelta(days=9), effective_to=W0),
        ),
    )
    found = _findings(data)
    assert found[AnomalyType.EXPIRED_SKILL_TREATED_AS_CURRENT.value] == {"ESK-000001"}


def test_stale_skill_is_informational_only():
    data = inputs(
        employees=(emp(1),), skill_versions=(skill(1, 1, verified=W1 - timedelta(days=900)),)
    )
    found = _findings(data)
    assert found == {AnomalyType.STALE_SKILL.value: {"ESK-000001"}}


def test_duplicate_demand_keeps_lowest_line_number():
    data = inputs(
        demand=(
            line(W1, 1, 40.0),
            line(W1, 2, 36.0),  # duplicate of line 1 (hours differ)
            line(W1, 3, 40.0, min_prof=4),  # different minimum proficiency: not a duplicate
            line(W1, 4, 40.0, status="DRAFT"),  # not counted (BR-DEM-003)
        )
    )
    result = AnalysisPipeline(ctx(), data).run()
    dup = {f.evaluation_key for f in result.detection.findings}
    assert dup == {"DEM-PRJ-2026-000001-2026W10-02"}
    assert {d.demand_id for d in result.selection.kept} == {
        "DEM-PRJ-2026-000001-2026W10-01",
        "DEM-PRJ-2026-000001-2026W10-03",
    }


def test_overlapping_assignment_conflict_needs_a_dedicated_allocation():
    data = inputs(
        employees=(emp(1), emp(2)),
        availability=(schedule(1), schedule(2)),
        allocations=(
            alloc(1, 1, W0, W1 + timedelta(days=6), 20.0, kind="DEDICATED"),
            alloc(2, 1, W1 + timedelta(days=6), W2, 10.0),  # overlaps on one day
            alloc(3, 1, W2, W3, 10.0),  # overlaps 2 only (both SHARED): no conflict
            alloc(4, 2, W0, W1, 10.0, kind="DEDICATED"),
            alloc(5, 2, W1 + timedelta(days=1), W2, 10.0),  # adjacent, no overlap
            alloc(6, 2, W0, W1, 10.0, status="CANCELLED"),  # not counted
        ),
    )
    found = _findings(data)
    assert found[AnomalyType.OVERLAPPING_ALLOCATION_CONFLICT.value] == {
        "ALLOC-2026-000001|ALLOC-2026-000002"
    }


def test_empty_inputs_produce_empty_results():
    result = AnalysisPipeline(ctx(), AnalysisInputs()).run()
    assert result.gaps.rows == [] and result.recommendations == []
    assert result.detection.findings == [] and result.forecast.rows == []
    assert result.forecast.evaluation["available"] is False


# ------------------------------------------------------------------ evaluation and leakage
def test_detection_scores_count_tp_fp_fn_tn():
    def f(key: str) -> Finding:
        return Finding(
            AnomalyType.DUPLICATE_DEMAND, "BR-DEM-004", "demand_plan", key, "MEDIUM", "", {}
        )

    result = evaluate_detection(
        [f("A"), f("B"), f("C")],
        {"DUPLICATE_DEMAND": 10},
        {"DUPLICATE_DEMAND": {"A", "B", "D", "E"}},
    )
    d = result["per_type"]["DUPLICATE_DEMAND"]
    assert (d["tp"], d["fp"], d["fn"], d["tn"]) == (2, 1, 2, 5)
    assert d["precision"] == round(2 / 3, 4) and d["recall"] == 0.5
    assert d["f1"] == round(2 * (2 / 3) * 0.5 / (2 / 3 + 0.5), 4)
    assert result["per_type"]["OVERLAPPING_ALLOCATION_CONFLICT"]["precision"] is None


def test_detection_code_never_reads_ground_truth():
    analytics = Path(__file__).resolve().parents[2] / "app" / "modules" / "analytics"
    for name in ("detection.py", "pipeline.py", "capacity.py", "demand.py", "skills.py"):
        source = (analytics / name).read_text(encoding="utf-8")
        assert "analytics.evaluation" not in source, name
        assert "ground_truth.csv" not in source and "GroundTruthSource" not in source, name

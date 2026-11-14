"""Pydantic v2 DTOs for analysis runs and their results."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.params import (
    DateWindow,
    DateWindowQuery,
    EmployeeId,
    PageQuery,
    ProjectId,
    RoleId,
    RunId,
    SkillId,
)
from app.domain.enums import (
    AnomalyType,
    FindingSeverity,
    FindingStatus,
    ForecastMethod,
    GapSeverity,
    HireType,
    RecommendationStatus,
    RecommendationType,
    RiskBand,
    RunStatus,
    RunType,
)


# ------------------------------------------------------------------ requests / queries
class RunCreate(BaseModel):
    """Start a full analysis run. All fields are optional."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of_date: date | None = Field(
        default=None,
        description="'Today' of the analysis; defaults to the dataset's as_of_date.",
    )
    demand_basis: Literal["PLANNED", "FORECAST"] = Field(
        default="PLANNED", description="Demand used for gaps (BR-GAP-009)."
    )
    forecast_method: ForecastMethod = Field(
        default=ForecastMethod.PLAN_RATIO, description="Method used for the FORECAST basis."
    )


class RunQuery(PageQuery):
    status: RunStatus | None = None
    run_type: RunType | None = None


class _InRun(BaseModel):
    run_id: RunId | None = Field(
        default=None, description="Analysis run; defaults to the latest successful run."
    )


class ForecastQuery(DateWindowQuery, _InRun):
    method: ForecastMethod | None = Field(
        default=None, description="Defaults to the run's forecast method."
    )
    project_id: ProjectId | None = None
    role_id: RoleId | None = None


class ForecastSummaryQuery(ForecastQuery):
    group_by: Literal["total", "project", "role", "skill"] = "role"
    period: Literal["week", "month"] = "week"
    skill_id: SkillId | None = Field(default=None, description="Only this primary skill.")


class CapacityQuery(DateWindow, _InRun):
    role_id: RoleId | None = None
    employee_id: EmployeeId | None = None
    group_by: Literal["week", "month", "role"] = "week"


class GapQuery(DateWindowQuery, _InRun):
    project_id: ProjectId | None = None
    role_id: RoleId | None = None
    skill_id: SkillId | None = None
    severity: GapSeverity | None = None
    only_gaps: bool = Field(default=False, description="Only rows with gap_hours > 0.")


class GapSummaryQuery(GapQuery):
    group_by: Literal["role", "skill", "role_skill", "project", "week", "month"] = "role_skill"


class FindingQuery(DateWindowQuery, _InRun):
    anomaly_type: AnomalyType | None = None
    severity: FindingSeverity | None = None
    entity_type: str | None = Field(default=None, max_length=40)
    entity_id: str | None = Field(default=None, max_length=40)
    status: FindingStatus | None = None


class RecommendationQuery(PageQuery, _InRun):
    recommendation_type: RecommendationType | None = None
    role_id: RoleId | None = None
    skill_id: SkillId | None = None
    project_id: ProjectId | None = None
    employee_id: EmployeeId | None = None
    status: RecommendationStatus | None = None


class RunRef(_InRun):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ------------------------------------------------------------------ responses
class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RunOut(_Out):
    run_id: str
    run_type: RunType
    status: RunStatus
    as_of_date: date
    period_start: date
    period_end: date
    rules_version: str
    rules_sha256: str
    parameters: dict[str, Any]
    summary: dict[str, Any] | None
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None
    triggered_by: str


class ForecastRowOut(_Out):
    run_id: str
    method: ForecastMethod
    project_id: str
    role_id: str
    week_start_date: date
    planned_hours: float
    forecast_hours: float


class ForecastGroupOut(BaseModel):
    group: str | None = Field(description="Project, role or skill ID (null for total/unplanned).")
    period: str = Field(description="ISO week (2026W10) or month (2026-03).")
    period_start: date
    weeks: int
    planned_hours: float
    forecast_hours: float
    forecast_fte: float


class CapacityGroupOut(BaseModel):
    group: str = Field(description="Week start, month (2026-03) or role ID.")
    weeks: int
    employee_weeks: int
    avg_headcount: float
    gross_hours: float
    leave_hours: float
    training_hours: float
    net_hours: float
    allocated_hours: float
    available_hours: float
    overallocated_hours: float
    part_time_and_partial_week_reduction_hours: float = Field(
        description="Standard hours (40 x employee-weeks) minus scheduled (gross) hours."
    )
    utilization: float | None
    fte_gross: float
    fte_net: float
    fte_allocated: float
    fte_available: float


class CapacitySummaryOut(BaseModel):
    run_id: str
    as_of_date: date
    totals: CapacityGroupOut | None
    risk_bands: dict[str, int]
    groups: list[CapacityGroupOut]


class GapOut(_Out):
    gap_id: str
    run_id: str
    project_id: str
    role_id: str
    skill_id: str
    iso_year: int
    iso_week: int
    week_start_date: date
    demand_hours: float
    committed_hours: float
    at_risk_hours: float
    gap_hours: float
    coverage_ratio: float
    reallocated_hours: float
    trained_hours: float
    hire_hours: float
    unresolved_hours: float
    severity: GapSeverity
    source_demand_ids: list[str]


class GapGroupOut(BaseModel):
    group: str
    rows: int
    weeks: int
    demand_hours: float
    committed_hours: float
    at_risk_hours: float
    gap_hours: float
    coverage_ratio: float | None
    gap_fte: float
    reallocated_hours: float
    trained_hours: float
    hire_hours: float
    unresolved_hours: float
    worst_severity: GapSeverity


class FindingOut(_Out):
    finding_id: str
    run_id: str
    anomaly_type: AnomalyType
    rule_id: str
    entity_type: str
    entity_id: str
    week_start_date: date | None
    related_ids: list[str]
    severity: FindingSeverity
    message: str
    details: dict[str, Any]
    status: FindingStatus


class EvaluationOut(BaseModel):
    run_id: str
    as_of_date: date
    evaluation: dict[str, Any]


class GapLinkOut(_Out):
    gap_id: str
    covered_hours: float


class RecommendationOut(_Out):
    recommendation_id: str
    run_id: str
    recommendation_type: RecommendationType
    hire_type: HireType | None
    role_id: str
    skill_id: str
    employee_id: str | None
    project_id: str | None
    period_start: date
    period_end: date
    hours: float
    headcount: int | None
    rank: int
    strategy_name: str
    rule_ids: list[str]
    explanation: str
    assumptions: dict[str, Any]
    source_refs: list[dict[str, str]]
    status: RecommendationStatus
    gap_links: list[GapLinkOut] = []


class WeekPointOut(BaseModel):
    week_start_date: date
    demand_hours: float
    forecast_hours: float
    committed_hours: float
    gap_hours: float
    net_hours: float
    allocated_hours: float
    utilization: float | None


class DashboardMetricsOut(BaseModel):
    run_id: str
    as_of_date: date
    window: dict[str, Any]
    capacity: dict[str, Any]
    demand: dict[str, Any]
    coverage: dict[str, Any]
    findings: dict[str, dict[str, int]]
    recommendations: dict[str, Any]
    forecast_accuracy: dict[str, Any]
    detection_evaluation: dict[str, Any]
    risk_bands: dict[RiskBand, int]
    top_gaps: list[GapGroupOut]
    weekly: list[WeekPointOut]

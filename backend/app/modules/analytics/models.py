"""Analysis output tables. Rows are immutable snapshots belonging to one analysis_run."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.constraints import between_check, date_order_check, id_format_check
from app.db.types import Hours, JSONType, Ratio, UTCDateTime, enum_type
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
from app.domain.ids import EntityKind

HOURS = {"units": "hours"}
RATIO = {"units": "ratio (0-1)"}
TOL = "0.01"  # hours tolerance for arithmetic identities (BR-CAP-009)


class AnalysisRun(TimestampMixin, Base):
    __tablename__ = "analysis_run"
    __table_args__ = (
        id_format_check("run_id", EntityKind.ANALYSIS_RUN),
        date_order_check("period_start", "period_end", name="period"),
        CheckConstraint("length(rules_sha256) = 64", name="rules_sha256_length"),
        CheckConstraint(
            "(status = 'RUNNING' AND finished_at IS NULL)"
            " OR (status <> 'RUNNING' AND finished_at IS NOT NULL)",
            name="finished_at_status",
        ),
        CheckConstraint("status = 'FAILED' OR error_message IS NULL", name="error_only_on_failure"),
        Index("ix_analysis_run_type_status", "run_type", "status"),
        {"comment": "One execution of forecasting / gap analysis / detection (A-31)."},
    )
    __immutable__ = ("run_type", "as_of_date", "period_start", "period_end", "rules_sha256")

    run_id: Mapped[str] = mapped_column(
        String(15), primary_key=True, comment="Immutable ID, RUN-<as_of year>-000001."
    )
    run_type: Mapped[RunType] = mapped_column(
        enum_type(RunType, "run_type"), comment="Kind of run."
    )
    status: Mapped[RunStatus] = mapped_column(
        enum_type(RunStatus, "run_status"), comment="RUNNING -> SUCCEEDED | FAILED."
    )
    as_of_date: Mapped[date] = mapped_column(
        Date, comment="'Today' for status derivation and forecast origin (A-02)."
    )
    period_start: Mapped[date] = mapped_column(Date, comment="First analysed week (Monday).")
    period_end: Mapped[date] = mapped_column(Date, comment="Last analysed day.")
    rules_version: Mapped[str] = mapped_column(String(20), comment="business_rules.toml version.")
    rules_sha256: Mapped[str] = mapped_column(
        String(64), comment="SHA-256 of business_rules.toml used (traceability)."
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONType, comment="Request parameters, e.g. demand basis and method."
    )
    summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONType, comment="Headline metrics (e.g. MAE/WAPE, counts)."
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), comment="Start time (UTC).")
    finished_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), comment="End time (UTC); null while RUNNING."
    )
    error_message: Mapped[str | None] = mapped_column(Text, comment="Failure reason (FAILED only).")
    triggered_by: Mapped[str] = mapped_column(String(100), comment="Actor who started the run.")

    gaps: Mapped[list[GapAnalysis]] = relationship(back_populates="run")
    recommendations: Mapped[list[Recommendation]] = relationship(back_populates="run")
    findings: Mapped[list[ExceptionFinding]] = relationship(back_populates="run")


class CapacitySnapshot(Base):
    __tablename__ = "capacity_snapshot"
    __table_args__ = (
        CheckConstraint(
            "gross_hours >= 0 AND leave_hours >= 0 AND training_hours >= 0"
            " AND net_hours >= 0 AND allocated_hours >= 0",
            name="non_negative_hours",
        ),
        CheckConstraint(
            f"ABS(net_hours - (gross_hours - leave_hours - training_hours)) <= {TOL}",
            name="net_identity",
        ),
        CheckConstraint(
            f"ABS(free_hours - (net_hours - allocated_hours)) <= {TOL}", name="free_identity"
        ),
        CheckConstraint(
            "(net_hours = 0 AND utilization IS NULL)"
            " OR (net_hours > 0 AND utilization IS NOT NULL)",
            name="utilization_defined",
        ),
        {"comment": "Per employee-week capacity facts (BR-CAP-003..009, BR-UTL-001/002)."},
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_run.run_id", ondelete="RESTRICT"), primary_key=True, comment="Run."
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
        comment="Employee.",
    )
    week_start_date: Mapped[date] = mapped_column(
        Date, primary_key=True, comment="Monday of the ISO week."
    )
    gross_hours: Mapped[Decimal] = mapped_column(
        Hours(), comment="Scheduled hours while employed (BR-CAP-003).", info=HOURS
    )
    leave_hours: Mapped[Decimal] = mapped_column(
        Hours(), comment="Approved leave deducted (BR-CAP-005).", info=HOURS
    )
    training_hours: Mapped[Decimal] = mapped_column(
        Hours(), comment="Training time deducted (BR-CAP-006).", info=HOURS
    )
    net_hours: Mapped[Decimal] = mapped_column(
        Hours(), comment="gross - leave - training (BR-CAP-007).", info=HOURS
    )
    allocated_hours: Mapped[Decimal] = mapped_column(
        Hours(), comment="Counted allocations, prorated (BR-CAP-008).", info=HOURS
    )
    free_hours: Mapped[Decimal] = mapped_column(
        Hours(), comment="net - allocated; negative = over-allocated (BR-CAP-009).", info=HOURS
    )
    utilization: Mapped[Decimal | None] = mapped_column(
        Ratio(),
        comment="allocated / net; null when net = 0 (BR-UTL-001).",
        info={"units": "ratio"},
    )
    risk_band: Mapped[RiskBand] = mapped_column(
        enum_type(RiskBand, "risk_band"), comment="Utilization band (BR-UTL-002)."
    )


class ForecastResult(Base):
    __tablename__ = "forecast_result"
    __table_args__ = (
        CheckConstraint("planned_hours >= 0 AND forecast_hours >= 0", name="non_negative_hours"),
        Index("ix_forecast_result_run_role_week", "run_id", "role_id", "week_start_date"),
        {"comment": "Forecast demand per run, method, project, role and week (BR-FCT-002)."},
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_run.run_id", ondelete="RESTRICT"), primary_key=True, comment="Run."
    )
    method: Mapped[ForecastMethod] = mapped_column(
        enum_type(ForecastMethod, "forecast_method"),
        primary_key=True,
        comment="Forecasting strategy (BR-FCT-003).",
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.project_id", ondelete="RESTRICT"),
        primary_key=True,
        comment="Project.",
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("role.role_id", ondelete="RESTRICT"), primary_key=True, comment="Role."
    )
    week_start_date: Mapped[date] = mapped_column(
        Date, primary_key=True, comment="Monday of the forecast week."
    )
    planned_hours: Mapped[Decimal] = mapped_column(
        Hours(9), comment="Planned (de-duplicated) hours used as input.", info=HOURS
    )
    forecast_hours: Mapped[Decimal] = mapped_column(Hours(9), comment="Forecast hours.", info=HOURS)


class GapAnalysis(Base):
    __tablename__ = "gap_analysis"
    __table_args__ = (
        id_format_check("gap_id", EntityKind.GAP),
        CheckConstraint("demand_hours > 0", name="demand_positive"),
        CheckConstraint(
            "committed_hours >= 0 AND at_risk_hours >= 0 AND gap_hours >= 0"
            " AND reallocated_hours >= 0 AND trained_hours >= 0 AND hire_hours >= 0"
            " AND unresolved_hours >= 0",
            name="non_negative_hours",
        ),
        CheckConstraint(f"committed_hours <= demand_hours + {TOL}", name="committed_le_demand"),
        CheckConstraint(
            f"ABS(gap_hours - (demand_hours - committed_hours)) <= {TOL}", name="gap_identity"
        ),
        CheckConstraint(
            f"ABS(reallocated_hours + trained_hours + hire_hours + unresolved_hours - gap_hours)"
            f" <= {TOL}",
            name="resolution_identity",
        ),
        CheckConstraint("coverage_ratio >= 0 AND coverage_ratio <= 1", name="coverage_range"),
        between_check("iso_week", 1, 53),
        Index(
            "uq_gap_analysis_grain",
            "run_id",
            "project_id",
            "role_id",
            "skill_id",
            "week_start_date",
            unique=True,
        ),
        Index("ix_gap_analysis_run_week", "run_id", "week_start_date"),
        Index("ix_gap_analysis_run_role_skill", "run_id", "role_id", "skill_id"),
        {"comment": "Coverage and gap per run x project x role x primary skill x week."},
    )

    gap_id: Mapped[str] = mapped_column(
        String(17), primary_key=True, comment="Immutable ID, GAP-<run seq>-<seq>."
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_run.run_id", ondelete="RESTRICT"), comment="Run."
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.project_id", ondelete="RESTRICT"), comment="Project."
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("role.role_id", ondelete="RESTRICT"), comment="Demanded role."
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skill.skill_id", ondelete="RESTRICT"), comment="Primary skill (A-14)."
    )
    iso_year: Mapped[int] = mapped_column(SmallInteger, comment="ISO-8601 year.")
    iso_week: Mapped[int] = mapped_column(SmallInteger, comment="ISO-8601 week.")
    week_start_date: Mapped[date] = mapped_column(Date, comment="Monday of the ISO week.")
    demand_hours: Mapped[Decimal] = mapped_column(
        Hours(9), comment="Counted, de-duplicated demand (BR-DEM-003/004).", info=HOURS
    )
    committed_hours: Mapped[Decimal] = mapped_column(
        Hours(9), comment="Covered by eligible allocated employees (BR-GAP-002).", info=HOURS
    )
    at_risk_hours: Mapped[Decimal] = mapped_column(
        Hours(9), comment="Allocated but ineligible (BR-GAP-003).", info=HOURS
    )
    gap_hours: Mapped[Decimal] = mapped_column(
        Hours(9), comment="demand - committed (BR-GAP-005).", info=HOURS
    )
    coverage_ratio: Mapped[Decimal] = mapped_column(
        Ratio(), comment="committed / demand.", info=RATIO
    )
    reallocated_hours: Mapped[Decimal] = mapped_column(
        Hours(9), comment="Gap resolved by REALLOCATE (BR-REC-002).", info=HOURS
    )
    trained_hours: Mapped[Decimal] = mapped_column(
        Hours(9), comment="Gap resolved by TRAIN (BR-REC-003).", info=HOURS
    )
    hire_hours: Mapped[Decimal] = mapped_column(
        Hours(9), comment="Gap resolved by HIRE (BR-REC-004).", info=HOURS
    )
    unresolved_hours: Mapped[Decimal] = mapped_column(
        Hours(9), comment="Gap left after all strategies.", info=HOURS
    )
    severity: Mapped[GapSeverity] = mapped_column(
        enum_type(GapSeverity, "gap_severity"), comment="Severity band (BR-GAP-006)."
    )
    source_demand_ids: Mapped[list[str]] = mapped_column(
        JSONType, comment="Demand lines aggregated into this row."
    )

    run: Mapped[AnalysisRun] = relationship(back_populates="gaps")
    recommendation_links: Mapped[list[RecommendationGapLink]] = relationship(back_populates="gap")


class Recommendation(TimestampMixin, Base):
    __tablename__ = "recommendation"
    __table_args__ = (
        id_format_check("recommendation_id", EntityKind.RECOMMENDATION),
        date_order_check("period_start", "period_end", name="period"),
        CheckConstraint("hours > 0", name="hours_positive"),
        CheckConstraint("rank >= 1", name="rank_positive"),
        CheckConstraint(
            "(recommendation_type = 'HIRE' AND hire_type IS NOT NULL AND headcount >= 1"
            " AND employee_id IS NULL)"
            " OR (recommendation_type <> 'HIRE' AND hire_type IS NULL AND headcount IS NULL"
            " AND employee_id IS NOT NULL)",
            name="type_fields",
        ),
        CheckConstraint(
            "recommendation_type <> 'REALLOCATE' OR project_id IS NOT NULL",
            name="reallocate_has_project",
        ),
        Index("ix_recommendation_run_type", "run_id", "recommendation_type"),
        {"comment": "Explainable REALLOCATE / TRAIN / HIRE actions (BR-REC-001..006)."},
    )
    __immutable__ = ("run_id", "recommendation_type")

    recommendation_id: Mapped[str] = mapped_column(
        String(17), primary_key=True, comment="Immutable ID, REC-<run seq>-<seq>."
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_run.run_id", ondelete="RESTRICT"), comment="Run."
    )
    recommendation_type: Mapped[RecommendationType] = mapped_column(
        enum_type(RecommendationType, "recommendation_type"), comment="Action type."
    )
    hire_type: Mapped[HireType | None] = mapped_column(
        enum_type(HireType, "hire_type"), comment="PERMANENT or CONTRACT (HIRE only)."
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("role.role_id", ondelete="RESTRICT"), comment="Role addressed."
    )
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skill.skill_id", ondelete="RESTRICT"), comment="Primary skill addressed."
    )
    employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        comment="Employee to reallocate or train (not HIRE).",
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("project.project_id", ondelete="RESTRICT"),
        comment="Receiving project (required for REALLOCATE).",
    )
    period_start: Mapped[date] = mapped_column(Date, comment="First week covered (Monday).")
    period_end: Mapped[date] = mapped_column(Date, comment="Last day covered.")
    hours: Mapped[Decimal] = mapped_column(
        Hours(9), comment="Hours reallocated / trained / to hire for.", info=HOURS
    )
    headcount: Mapped[int | None] = mapped_column(
        SmallInteger, comment="People to hire (HIRE only, BR-REC-004).", info={"units": "people"}
    )
    rank: Mapped[int] = mapped_column(SmallInteger, comment="Deterministic display order in run.")
    strategy_name: Mapped[str] = mapped_column(
        String(40), comment="Strategy class that produced it."
    )
    rule_ids: Mapped[list[str]] = mapped_column(JSONType, comment="Business rules applied.")
    explanation: Mapped[str] = mapped_column(Text, comment="Human-readable reasoning.")
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSONType, comment="Parameter values used.")
    source_refs: Mapped[list[dict[str, str]]] = mapped_column(
        JSONType, comment="Source records [{type, id}] (BR-REC-005)."
    )
    status: Mapped[RecommendationStatus] = mapped_column(
        enum_type(RecommendationStatus, "recommendation_status"),
        index=True,
        comment="Review lifecycle (BR-REC-006).",
    )

    run: Mapped[AnalysisRun] = relationship(back_populates="recommendations")
    gap_links: Mapped[list[RecommendationGapLink]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan"
    )


class RecommendationGapLink(Base):
    """Bridge Recommendation <-> GapAnalysis (M:N)."""

    __tablename__ = "recommendation_gap_link"
    __table_args__ = (
        CheckConstraint("covered_hours > 0", name="covered_hours_positive"),
        {"comment": "Which gap rows a recommendation addresses, and by how many hours."},
    )

    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("recommendation.recommendation_id", ondelete="RESTRICT"),
        primary_key=True,
        comment="Recommendation.",
    )
    gap_id: Mapped[str] = mapped_column(
        ForeignKey("gap_analysis.gap_id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
        comment="Gap row addressed.",
    )
    covered_hours: Mapped[Decimal] = mapped_column(
        Hours(9), comment="Gap hours this recommendation resolves.", info=HOURS
    )

    recommendation: Mapped[Recommendation] = relationship(back_populates="gap_links")
    gap: Mapped[GapAnalysis] = relationship(back_populates="recommendation_links")


class ExceptionFinding(TimestampMixin, Base):
    __tablename__ = "exception_finding"
    __table_args__ = (
        id_format_check("finding_id", EntityKind.FINDING),
        CheckConstraint("rule_id LIKE 'BR-%' AND length(rule_id) = 10", name="rule_id_format"),
        Index("ix_exception_finding_run_type", "run_id", "anomaly_type"),
        Index("ix_exception_finding_entity", "entity_type", "entity_id"),
        {"comment": "Detected anomalies (BR-UTL-004, BR-SKL-004, BR-DEM-004, BR-ALC-003)."},
    )
    __immutable__ = ("run_id", "anomaly_type", "rule_id", "entity_type", "entity_id")

    finding_id: Mapped[str] = mapped_column(
        String(17), primary_key=True, comment="Immutable ID, EXC-<run seq>-<seq>."
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_run.run_id", ondelete="RESTRICT"), comment="Run."
    )
    anomaly_type: Mapped[AnomalyType] = mapped_column(
        enum_type(AnomalyType, "anomaly_type"), comment="Detected anomaly type."
    )
    rule_id: Mapped[str] = mapped_column(String(10), comment="Detecting business rule.")
    entity_type: Mapped[str] = mapped_column(
        String(40), comment="Table of the primary record (e.g. employee_skill)."
    )
    entity_id: Mapped[str] = mapped_column(String(40), comment="ID of the primary record.")
    week_start_date: Mapped[date | None] = mapped_column(
        Date, comment="Affected week, for week-based anomalies."
    )
    related_ids: Mapped[list[str]] = mapped_column(
        JSONType, comment="Other records involved (e.g. both allocations)."
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        enum_type(FindingSeverity, "finding_severity"), comment="Severity."
    )
    message: Mapped[str] = mapped_column(Text, comment="Human-readable description.")
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONType, comment="Numbers behind the finding (e.g. allocated vs net hours)."
    )
    status: Mapped[FindingStatus] = mapped_column(
        enum_type(FindingStatus, "finding_status"),
        index=True,
        comment="Review lifecycle.",
    )

    run: Mapped[AnalysisRun] = relationship(back_populates="findings")

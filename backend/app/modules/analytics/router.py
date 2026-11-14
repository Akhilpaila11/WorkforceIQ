"""Analysis endpoints: run the pipeline and read forecasts, capacity, gaps, findings,
recommendations and dashboard metrics. Every result endpoint takes an optional ``run_id``
(default: the latest successful run)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query, status

from app.api import deps
from app.core.errors import ERROR_RESPONSES, ErrorResponse
from app.core.params import RECOMMENDATION_ID, RUN_ID, PageOut
from app.modules.analytics.schemas import (
    CapacityQuery,
    CapacitySummaryOut,
    DashboardMetricsOut,
    EvaluationOut,
    FindingOut,
    FindingQuery,
    ForecastGroupOut,
    ForecastQuery,
    ForecastRowOut,
    ForecastSummaryQuery,
    GapGroupOut,
    GapOut,
    GapQuery,
    GapSummaryQuery,
    RecommendationOut,
    RecommendationQuery,
    RunCreate,
    RunOut,
    RunQuery,
    RunRef,
)
from app.modules.analytics.services import (
    AnalysisRunService,
    CapacityService,
    DashboardService,
    FindingService,
    ForecastService,
    GapService,
    RecommendationService,
    RunResolver,
)

RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    409: {"model": ErrorResponse, "description": "The run has not succeeded (no results)"},
}
router = APIRouter(responses=RESPONSES)
RunPath = Annotated[str, Path(pattern=RUN_ID, examples=["RUN-2026-000001"])]


@router.post("/analysis/runs", status_code=status.HTTP_201_CREATED, tags=["analysis"])
def create_run(
    service: Annotated[AnalysisRunService, Depends(deps.analysis_run_service)],
    body: Annotated[RunCreate | None, Body()] = None,
) -> RunOut:
    """Run the full pipeline (capacity, forecast, gaps, recommendations, detection,
    evaluation) synchronously and store every result under a new run ID."""
    return RunOut.model_validate(service.start(body or RunCreate()))


@router.get("/analysis/runs", tags=["analysis"])
def list_runs(
    query: Annotated[RunQuery, Query()],
    runs: Annotated[RunResolver, Depends(deps.run_resolver)],
) -> PageOut[RunOut]:
    return PageOut[RunOut].of(runs.list(query))


@router.get("/analysis/runs/{run_id}", tags=["analysis"])
def get_run(run_id: RunPath, runs: Annotated[RunResolver, Depends(deps.run_resolver)]) -> RunOut:
    """Status, parameters, rules version/hash and headline summary of one run."""
    return RunOut.model_validate(runs.get(run_id))


@router.get("/forecasts/results", tags=["forecasts"])
def forecast_results(
    query: Annotated[ForecastQuery, Query()],
    service: Annotated[ForecastService, Depends(deps.forecast_service)],
) -> PageOut[ForecastRowOut]:
    """Forecast per project, role and week (BR-FCT-002) next to the planned hours."""
    return PageOut[ForecastRowOut].of(service.results(query))


@router.get("/forecasts/summary", tags=["forecasts"])
def forecast_summary(
    query: Annotated[ForecastSummaryQuery, Query()],
    service: Annotated[ForecastService, Depends(deps.forecast_service)],
) -> PageOut[ForecastGroupOut]:
    """Forecast rolled up by total, project, role or primary skill, per week or month."""
    return PageOut[ForecastGroupOut].of(service.summary(query))


@router.get("/forecasts/evaluation", tags=["forecasts"])
def forecast_evaluation(
    query: Annotated[RunRef, Query()],
    runs: Annotated[RunResolver, Depends(deps.run_resolver)],
) -> EvaluationOut:
    """MAE, WAPE and BIAS per method on hold-out weeks with actuals (BR-FCT-005)."""
    run = runs.resolve(query.run_id)
    evaluation = (run.summary or {}).get("forecast", {}).get("evaluation", {})
    return EvaluationOut(run_id=run.run_id, as_of_date=run.as_of_date, evaluation=evaluation)


@router.get("/capacity/summary", tags=["capacity"])
def capacity_summary(
    query: Annotated[CapacityQuery, Query()],
    service: Annotated[CapacityService, Depends(deps.capacity_service)],
) -> CapacitySummaryOut:
    """Gross, leave, training, net, allocated and available hours, utilization and FTE."""
    return service.summary(query)


@router.get("/gap-analysis", tags=["gap analysis"])
def gap_rows(
    query: Annotated[GapQuery, Query()],
    service: Annotated[GapService, Depends(deps.gap_service)],
) -> PageOut[GapOut]:
    """Coverage and gap per project, role, primary skill and week, with its resolution."""
    return PageOut[GapOut].of(service.rows(query))


@router.get("/gap-analysis/summary", tags=["gap analysis"])
def gap_summary(
    query: Annotated[GapSummaryQuery, Query()],
    service: Annotated[GapService, Depends(deps.gap_service)],
) -> PageOut[GapGroupOut]:
    """Gaps summed by role, skill, project, week or month; ratios recomputed (BR-GAP-007)."""
    return PageOut[GapGroupOut].of(service.summary(query))


@router.get("/exceptions", tags=["exceptions"])
def exceptions(
    query: Annotated[FindingQuery, Query()],
    service: Annotated[FindingService, Depends(deps.finding_service)],
) -> PageOut[FindingOut]:
    """Detected anomalies with rule ID, records involved and the numbers behind them."""
    return PageOut[FindingOut].of(service.list(query))


@router.get("/exceptions/evaluation", tags=["exceptions"])
def exception_evaluation(
    query: Annotated[RunRef, Query()],
    service: Annotated[FindingService, Depends(deps.finding_service)],
) -> EvaluationOut:
    """Precision, recall and F1 (TP/FP/FN/TN) of detection against the separate ground truth."""
    run, evaluation = service.evaluation(query.run_id)
    return EvaluationOut(run_id=run.run_id, as_of_date=run.as_of_date, evaluation=evaluation)


@router.get("/recommendations", tags=["recommendations"])
def recommendations(
    query: Annotated[RecommendationQuery, Query()],
    service: Annotated[RecommendationService, Depends(deps.recommendation_service)],
) -> PageOut[RecommendationOut]:
    """REALLOCATE / TRAIN / HIRE actions with rule IDs, explanation and linked gap rows."""
    return PageOut[RecommendationOut].of(service.list(query))


@router.get("/recommendations/{recommendation_id}", tags=["recommendations"])
def recommendation(
    recommendation_id: Annotated[str, Path(pattern=RECOMMENDATION_ID)],
    service: Annotated[RecommendationService, Depends(deps.recommendation_service)],
) -> RecommendationOut:
    return service.get(recommendation_id)


@router.get("/dashboard/metrics", tags=["dashboard"])
def dashboard_metrics(
    query: Annotated[RunRef, Query()],
    service: Annotated[DashboardService, Depends(deps.dashboard_service)],
) -> DashboardMetricsOut:
    """Headline metrics and weekly demand / capacity series for the dashboard."""
    return service.metrics(query.run_id)

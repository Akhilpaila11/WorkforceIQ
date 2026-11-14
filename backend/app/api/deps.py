"""Composition root: the only place that wires concrete repositories into services.

FastAPI builds one database session per request (unit of work: commit on success, rollback
on error) and passes it to the service factories below through ``Depends``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import session_scope
from app.domain.rules_config import RulesConfig
from app.modules.analytics.evaluation import GroundTruthSource
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
from app.modules.analytics.sql_repositories import (
    SqlCapacityRepository,
    SqlFindingRepository,
    SqlForecastRepository,
    SqlGapRepository,
    SqlRecommendationRepository,
    SqlRunRepository,
)
from app.modules.projects.models import Allocation, DemandPlan, Project
from app.modules.projects.schemas import AllocationQuery, DemandQuery, ProjectQuery
from app.modules.projects.sql_repositories import (
    SqlAllocationRepository,
    SqlDemandRepository,
    SqlProjectRepository,
)
from app.modules.queries import ChildQueryService, QueryService
from app.modules.reporting.services import SummaryService
from app.modules.reporting.sql_repositories import SqlStatsRepository
from app.modules.workforce.models import (
    Availability,
    Employee,
    EmployeeSkill,
    Role,
    Skill,
    Training,
)
from app.modules.workforce.schemas import (
    AvailabilityQuery,
    EmployeeQuery,
    EmployeeSkillQuery,
    RoleQuery,
    SkillQuery,
    TrainingQuery,
)
from app.modules.workforce.sql_repositories import (
    SqlAvailabilityRepository,
    SqlEmployeeRepository,
    SqlEmployeeSkillRepository,
    SqlRoleRepository,
    SqlSkillRepository,
    SqlTrainingRepository,
)


def get_session(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    with session_scope(factory) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def employee_service(session: SessionDep) -> QueryService[Employee, EmployeeQuery]:
    return QueryService(SqlEmployeeRepository(session), entity="employee")


def employee_skill_service(
    session: SessionDep,
) -> ChildQueryService[EmployeeSkill, EmployeeSkillQuery]:
    return ChildQueryService(
        SqlEmployeeRepository(session),
        SqlEmployeeSkillRepository(session),
        parent_entity="employee",
    )


def role_service(session: SessionDep) -> QueryService[Role, RoleQuery]:
    return QueryService(SqlRoleRepository(session), entity="role")


def skill_service(session: SessionDep) -> QueryService[Skill, SkillQuery]:
    return QueryService(SqlSkillRepository(session), entity="skill")


def availability_service(session: SessionDep) -> QueryService[Availability, AvailabilityQuery]:
    return QueryService(SqlAvailabilityRepository(session), entity="availability")


def training_service(session: SessionDep) -> QueryService[Training, TrainingQuery]:
    return QueryService(SqlTrainingRepository(session), entity="training")


def project_service(session: SessionDep) -> QueryService[Project, ProjectQuery]:
    return QueryService(SqlProjectRepository(session), entity="project")


def demand_service(session: SessionDep) -> ChildQueryService[DemandPlan, DemandQuery]:
    return ChildQueryService(
        SqlProjectRepository(session), SqlDemandRepository(session), parent_entity="project"
    )


def allocation_service(session: SessionDep) -> QueryService[Allocation, AllocationQuery]:
    return QueryService(SqlAllocationRepository(session), entity="allocation")


def summary_service(session: SessionDep) -> SummaryService:
    return SummaryService(SqlStatsRepository(session))


# ------------------------------------------------------------------ analytics (Phase 5)
def get_rules(request: Request) -> RulesConfig:
    rules: RulesConfig = request.app.state.rules
    return rules


def analysis_run_service(
    request: Request, rules: Annotated[RulesConfig, Depends(get_rules)]
) -> AnalysisRunService:
    settings = request.app.state.settings
    return AnalysisRunService(
        request.app.state.session_factory,
        rules=rules,
        ground_truth=GroundTruthSource(settings.resolve_path(settings.data_output_dir)),
        request_id=getattr(request.state, "request_id", None),
    )


def run_resolver(session: SessionDep) -> RunResolver:
    return RunResolver(SqlRunRepository(session))


Runs = Annotated[RunResolver, Depends(run_resolver)]


def forecast_service(session: SessionDep, runs: Runs) -> ForecastService:
    return ForecastService(runs, SqlForecastRepository(session))


def capacity_service(session: SessionDep, runs: Runs) -> CapacityService:
    return CapacityService(runs, SqlCapacityRepository(session))


def gap_service(session: SessionDep, runs: Runs) -> GapService:
    return GapService(runs, SqlGapRepository(session))


def finding_service(session: SessionDep, runs: Runs) -> FindingService:
    return FindingService(runs, SqlFindingRepository(session))


def recommendation_service(session: SessionDep, runs: Runs) -> RecommendationService:
    return RecommendationService(runs, SqlRecommendationRepository(session))


def dashboard_service(session: SessionDep, runs: Runs) -> DashboardService:
    return DashboardService(
        runs,
        SqlCapacityRepository(session),
        GapService(runs, SqlGapRepository(session)),
        SqlForecastRepository(session),
        SqlFindingRepository(session),
    )

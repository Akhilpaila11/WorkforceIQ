"""Import every ORM model so ``Base.metadata`` knows all 22 tables.

Alembic, the data-dictionary generator and tests import ``metadata`` from here.
"""

from __future__ import annotations

from app.db.base import Base
from app.db.models import AuditEvent, DatasetMetadata, IdSequence
from app.modules.analytics.models import (
    AnalysisRun,
    CapacitySnapshot,
    ExceptionFinding,
    ForecastResult,
    GapAnalysis,
    Recommendation,
    RecommendationGapLink,
)
from app.modules.projects.models import (
    Allocation,
    DemandActual,
    DemandPlan,
    DemandSkillRequirement,
    Project,
)
from app.modules.workforce.models import (
    Availability,
    Employee,
    EmployeeSkill,
    Role,
    RoleSkill,
    Skill,
    Training,
)

metadata = Base.metadata

#: The ten mandatory entities of the brief.
MANDATORY_MODELS: tuple[type[Base], ...] = (
    Employee,
    Role,
    Skill,
    EmployeeSkill,
    Project,
    DemandPlan,
    Allocation,
    Availability,
    Training,
    GapAnalysis,
)

SUPPORTING_MODELS: tuple[type[Base], ...] = (
    RoleSkill,
    DemandSkillRequirement,
    DemandActual,
    AnalysisRun,
    CapacitySnapshot,
    ForecastResult,
    Recommendation,
    RecommendationGapLink,
    ExceptionFinding,
    AuditEvent,
    DatasetMetadata,
    IdSequence,
)

ALL_MODELS: tuple[type[Base], ...] = MANDATORY_MODELS + SUPPORTING_MODELS

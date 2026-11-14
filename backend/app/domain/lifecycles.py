"""Allowed lifecycle transitions (docs/05-data-model.md section 6).

Services call :func:`assert_transition` before changing a status; the database stores the
status but does not know the transition graph.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from app.domain.enums import (
    AllocationStatus,
    AvailabilityStatus,
    DemandStatus,
    EmployeeStatus,
    FindingStatus,
    ProjectStatus,
    RecommendationStatus,
    RunStatus,
    TrainingStatus,
)
from app.domain.errors import InvalidStateTransition

Transitions = Mapping[StrEnum, frozenset[StrEnum]]


def _graph(edges: dict[StrEnum, set[StrEnum]], states: type[StrEnum]) -> Transitions:
    graph: dict[StrEnum, frozenset[StrEnum]] = {s: frozenset() for s in states}
    graph.update({k: frozenset(v) for k, v in edges.items()})
    return graph


E, P, D, A = EmployeeStatus, ProjectStatus, DemandStatus, AllocationStatus
V, T, R, C, F = (
    AvailabilityStatus,
    TrainingStatus,
    RecommendationStatus,
    RunStatus,
    FindingStatus,
)

LIFECYCLES: dict[type[StrEnum], Transitions] = {
    EmployeeStatus: _graph(
        {E.PENDING_START: {E.ACTIVE, E.TERMINATED}, E.ACTIVE: {E.TERMINATED}}, EmployeeStatus
    ),
    ProjectStatus: _graph(
        {
            P.PROPOSED: {P.APPROVED, P.CANCELLED},
            P.APPROVED: {P.ACTIVE, P.ON_HOLD, P.CANCELLED},
            P.ACTIVE: {P.ON_HOLD, P.COMPLETED, P.CANCELLED},
            P.ON_HOLD: {P.ACTIVE, P.CANCELLED},
        },
        ProjectStatus,
    ),
    DemandStatus: _graph(
        {
            D.DRAFT: {D.SUBMITTED, D.CANCELLED},
            D.SUBMITTED: {D.APPROVED, D.REJECTED, D.CANCELLED},
            D.APPROVED: {D.CANCELLED},
        },
        DemandStatus,
    ),
    AllocationStatus: _graph(
        {
            A.PROPOSED: {A.CONFIRMED, A.CANCELLED},
            A.CONFIRMED: {A.COMPLETED, A.CANCELLED},
        },
        AllocationStatus,
    ),
    AvailabilityStatus: _graph(
        {
            V.REQUESTED: {V.APPROVED, V.REJECTED, V.CANCELLED},
            V.APPROVED: {V.CANCELLED},
        },
        AvailabilityStatus,
    ),
    TrainingStatus: _graph(
        {
            T.PLANNED: {T.IN_PROGRESS, T.CANCELLED},
            T.IN_PROGRESS: {T.COMPLETED, T.CANCELLED},
        },
        TrainingStatus,
    ),
    RecommendationStatus: _graph(
        {R.PROPOSED: {R.ACCEPTED, R.REJECTED}, R.ACCEPTED: {R.IMPLEMENTED}},
        RecommendationStatus,
    ),
    RunStatus: _graph({C.RUNNING: {C.SUCCEEDED, C.FAILED}}, RunStatus),
    FindingStatus: _graph(
        {
            F.OPEN: {F.ACKNOWLEDGED, F.RESOLVED, F.DISMISSED},
            F.ACKNOWLEDGED: {F.RESOLVED, F.DISMISSED},
        },
        FindingStatus,
    ),
}


def allowed_next(current: StrEnum) -> frozenset[StrEnum]:
    return LIFECYCLES[type(current)][current]


def is_terminal(state: StrEnum) -> bool:
    return not allowed_next(state)


def is_transition_allowed(current: StrEnum, requested: StrEnum) -> bool:
    if type(current) is not type(requested):
        return False
    return requested in allowed_next(current)


def assert_transition(entity: str, current: StrEnum, requested: StrEnum) -> None:
    if not is_transition_allowed(current, requested):
        raise InvalidStateTransition(entity, str(current), str(requested))

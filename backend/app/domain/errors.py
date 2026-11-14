"""Domain exceptions. They carry a stable ``code`` and are mapped to HTTP status codes
centrally in Phase 4 (NotFound -> 404, Conflict/BusinessRule/StateTransition/Immutable -> 409,
DomainValidation -> 422). Nothing here knows about HTTP."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    code: str = "DOMAIN_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}


class NotFoundError(DomainError):
    code = "NOT_FOUND"

    def __init__(self, entity: str, entity_id: str) -> None:
        super().__init__(
            f"{entity} {entity_id} was not found",
            details={"entity": entity, "id": entity_id},
        )


class ConflictError(DomainError):
    code = "CONFLICT"


class DomainValidationError(DomainError):
    code = "VALIDATION_ERROR"


class BusinessRuleViolation(DomainError):
    code = "BUSINESS_RULE_VIOLATION"

    def __init__(self, rule_id: str, message: str, **details: Any) -> None:
        super().__init__(message, details={"rule_id": rule_id, **details})
        self.rule_id = rule_id


class InvalidStateTransition(DomainError):
    code = "INVALID_STATE_TRANSITION"

    def __init__(self, entity: str, current: str, requested: str) -> None:
        super().__init__(
            f"{entity} cannot move from {current} to {requested}",
            details={"entity": entity, "from": current, "to": requested},
        )


class ImmutableFieldError(DomainError):
    code = "IMMUTABLE_FIELD"

    def __init__(self, entity: str, field: str) -> None:
        super().__init__(
            f"{entity}.{field} is immutable once created",
            details={"entity": entity, "field": field},
        )

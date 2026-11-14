"""Every allowed value used in the data model (docs/05-data-model.md).

Enums are ``StrEnum`` so their value equals their name and they serialise as plain strings
(JSON, CSV, database ``VARCHAR`` + ``CHECK`` constraint).
"""

from __future__ import annotations

from enum import StrEnum


# --------------------------------------------------------------------------- workforce
class RoleFamily(StrEnum):
    ENGINEERING = "ENGINEERING"
    DATA = "DATA"
    CLOUD_INFRA = "CLOUD_INFRA"
    QUALITY = "QUALITY"
    DESIGN = "DESIGN"
    PRODUCT = "PRODUCT"
    DELIVERY = "DELIVERY"
    SECURITY = "SECURITY"


class SkillCategory(StrEnum):
    PROGRAMMING = "PROGRAMMING"
    DATA_ANALYTICS = "DATA_ANALYTICS"
    CLOUD = "CLOUD"
    DEVOPS = "DEVOPS"
    SECURITY = "SECURITY"
    TESTING = "TESTING"
    DESIGN = "DESIGN"
    MANAGEMENT = "MANAGEMENT"
    ARCHITECTURE = "ARCHITECTURE"
    DOMAIN = "DOMAIN"


class SkillImportance(StrEnum):
    CORE = "CORE"
    SUPPORTING = "SUPPORTING"


class Seniority(StrEnum):
    JUNIOR = "JUNIOR"
    MID = "MID"
    SENIOR = "SENIOR"
    LEAD = "LEAD"
    PRINCIPAL = "PRINCIPAL"


class EmployeeStatus(StrEnum):
    PENDING_START = "PENDING_START"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class AssessmentSource(StrEnum):
    SELF = "SELF"
    MANAGER = "MANAGER"
    ASSESSMENT = "ASSESSMENT"
    CERTIFICATION = "CERTIFICATION"
    TRAINING = "TRAINING"


class RecordedSkillStatus(StrEnum):
    """Status flag as recorded by the source HR system - never trusted (BR-SKL-003)."""

    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"


class EffectiveSkillStatus(StrEnum):
    """Status derived from dates (BR-SKL-002). Computed, never stored."""

    VALID = "VALID"
    STALE = "STALE"
    PENDING = "PENDING"
    EXPIRED = "EXPIRED"


class AvailabilityType(StrEnum):
    WORK_SCHEDULE = "WORK_SCHEDULE"
    ANNUAL_LEAVE = "ANNUAL_LEAVE"
    SICK_LEAVE = "SICK_LEAVE"
    PARENTAL_LEAVE = "PARENTAL_LEAVE"
    UNPAID_LEAVE = "UNPAID_LEAVE"
    OTHER_ABSENCE = "OTHER_ABSENCE"


class AvailabilityStatus(StrEnum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TrainingType(StrEnum):
    COURSE = "COURSE"
    CERTIFICATION = "CERTIFICATION"
    RECERTIFICATION = "RECERTIFICATION"
    MENTORING = "MENTORING"


class TrainingStatus(StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------- projects
class ProjectPriority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ProjectStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DemandStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DemandSource(StrEnum):
    PROJECT_PLAN = "PROJECT_PLAN"
    MANUAL = "MANUAL"
    IMPORT = "IMPORT"


class RequirementType(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class ActualSource(StrEnum):
    SYNTHETIC_TIMESHEET = "SYNTHETIC_TIMESHEET"
    TIMESHEET = "TIMESHEET"


class AllocationType(StrEnum):
    DEDICATED = "DEDICATED"
    SHARED = "SHARED"


class AllocationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------- analytics
class RunType(StrEnum):
    FORECAST = "FORECAST"
    GAP_ANALYSIS = "GAP_ANALYSIS"
    EXCEPTION_DETECTION = "EXCEPTION_DETECTION"
    FULL_PIPELINE = "FULL_PIPELINE"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class RiskBand(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    UNDER_UTILIZED = "UNDER_UTILIZED"
    HEALTHY = "HEALTHY"
    HIGH = "HIGH"
    OVERALLOCATED = "OVERALLOCATED"


class ForecastMethod(StrEnum):
    NAIVE_PLAN = "NAIVE_PLAN"
    MOVING_AVERAGE = "MOVING_AVERAGE"
    PLAN_RATIO = "PLAN_RATIO"


class GapSeverity(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecommendationType(StrEnum):
    REALLOCATE = "REALLOCATE"
    TRAIN = "TRAIN"
    HIRE = "HIRE"


class HireType(StrEnum):
    PERMANENT = "PERMANENT"
    CONTRACT = "CONTRACT"


class RecommendationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    IMPLEMENTED = "IMPLEMENTED"


class AnomalyType(StrEnum):
    ALLOCATION_EXCEEDS_AVAILABILITY = "ALLOCATION_EXCEEDS_AVAILABILITY"
    EXPIRED_SKILL_TREATED_AS_CURRENT = "EXPIRED_SKILL_TREATED_AS_CURRENT"
    DUPLICATE_DEMAND = "DUPLICATE_DEMAND"
    OVERLAPPING_ALLOCATION_CONFLICT = "OVERLAPPING_ALLOCATION_CONFLICT"
    STALE_SKILL = "STALE_SKILL"  # informational; not part of ground-truth evaluation


class FindingSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


# --------------------------------------------------------------------------- platform
class AuditAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    STATUS_CHANGE = "STATUS_CHANGE"
    DELETE = "DELETE"

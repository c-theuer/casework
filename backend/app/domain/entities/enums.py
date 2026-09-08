from enum import StrEnum


class Route(StrEnum):
    CRITICAL = "critical"
    ELEVATED = "elevated"
    LOW = "low"


class CaseStatus(StrEnum):
    AUTO_ESCALATED = "auto_escalated"
    PENDING_REVIEW = "pending_review"
    CLOSED = "closed"
    ERROR = "error"


class Resolution(StrEnum):
    APPROVED = "approved"
    DENIED = "denied"
    NONE = "none"


class CaseSource(StrEnum):
    LIVE_STRIPE = "live_stripe"
    BULK_SYNTHETIC = "bulk_synthetic"
    EVAL = "eval"
    INTEGRATION_TEST = "integration_test"


class CaseEventType(StrEnum):
    CREATED = "created"
    TRIAGED = "triaged"
    RESEARCHED = "researched"
    SYNTHESIZED = "synthesized"
    AUTO_ESCALATED = "auto_escalated"
    QUEUED_FOR_REVIEW = "queued_for_review"
    NOTIFIED = "notified"
    APPROVED = "approved"
    DENIED = "denied"
    ACTION_EXECUTED = "action_executed"
    LOGGED_ONLY = "logged_only"
    ROUTE_RECOMMENDATION_MISMATCH = "route_recommendation_mismatch"
    PAYMENT_CAPTURED = "payment_captured"
    PAYMENT_CANCELLED = "payment_cancelled"
    ERROR = "error"

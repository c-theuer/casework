from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.entities.enums import CaseSource, CaseStatus, Resolution, Route


class Case(BaseModel):
    """The base DTO for the cases resource. This is what flows router ->
    service -> repository (and back): routers never see the SQLAlchemy
    model, and neither do domain services -- only the concrete
    infrastructure repository does, converting to/from this shape
    internally.

    case_id/created_at/updated_at are None for a case that hasn't been
    persisted yet (i.e. the DTO a service builds to pass to
    CasesRepository.create()); the repository populates them from the
    inserted row before returning.
    """

    model_config = ConfigDict(from_attributes=True)

    case_id: UUID | None = None
    signal_id: str
    account_id: str
    signal_type: Literal["transaction", "login", "chargeback"]
    occurred_at: datetime
    upstream_score: float
    flag_reason: str
    payload: dict

    pattern: str | None = None
    triage_tier: str | None = None
    confidence: float | None = None
    entities: dict | None = None

    matched_rules: list[str] | None = None
    similar_cases: list[str] | None = None
    evidence: list[str] | None = None

    risk_score: float | None = None
    recommended_action: str | None = None
    draft_note: str | None = None

    route: Route | None = None
    status: CaseStatus
    resolution: Resolution = Resolution.NONE
    approved_by: str | None = None

    stripe_payment_intent_id: str | None = None
    source: CaseSource

    created_at: datetime | None = None
    updated_at: datetime | None = None

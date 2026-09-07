from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.models.base import Base


class Case(Base):
    __tablename__ = "cases"

    case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    signal_id: Mapped[str] = mapped_column(unique=True)
    account_id: Mapped[str]
    signal_type: Mapped[str]
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    upstream_score: Mapped[float]
    flag_reason: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSONB)

    pattern: Mapped[str | None]
    triage_tier: Mapped[str | None]
    confidence: Mapped[float | None]
    entities: Mapped[dict | None] = mapped_column(JSONB)

    matched_rules: Mapped[list | None] = mapped_column(JSONB)
    similar_cases: Mapped[list | None] = mapped_column(JSONB)
    evidence: Mapped[list | None] = mapped_column(JSONB)

    risk_score: Mapped[float | None]
    recommended_action: Mapped[str | None]
    draft_note: Mapped[str | None]

    route: Mapped[str | None]
    status: Mapped[str]
    resolution: Mapped[str] = mapped_column(default="none")
    approved_by: Mapped[str | None]

    stripe_payment_intent_id: Mapped[str | None]
    source: Mapped[str]

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

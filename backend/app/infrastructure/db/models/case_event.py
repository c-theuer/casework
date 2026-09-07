from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.models.base import Base


class CaseEvent(Base):
    __tablename__ = "case_events"

    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id", ondelete="CASCADE")
    )
    event_type: Mapped[str]
    event_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

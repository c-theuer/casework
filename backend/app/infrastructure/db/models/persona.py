from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.models.base import Base


class Persona(Base):
    __tablename__ = "personas"

    account_id: Mapped[str] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    tenure_days: Mapped[int]
    lifetime_volume_cents: Mapped[int]
    prior_case_count: Mapped[int] = mapped_column(default=0)
    default_device_context: Mapped[str]
    default_geo_context: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

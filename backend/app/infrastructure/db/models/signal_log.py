from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.models.base import Base


class SignalLog(Base):
    __tablename__ = "signals_log"

    signal_id: Mapped[str] = mapped_column(primary_key=True)
    account_id: Mapped[str]
    device_context: Mapped[str | None]
    geo_context: Mapped[str | None]
    signal_type: Mapped[str]
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str]
    raw_signal: Mapped[dict] = mapped_column(JSONB)

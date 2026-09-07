from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.models.base import Base


class Rule(Base):
    __tablename__ = "rules"

    rule_id: Mapped[str] = mapped_column(primary_key=True)
    pattern: Mapped[str | None]
    title: Mapped[str]
    description: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

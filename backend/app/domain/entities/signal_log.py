from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.entities.enums import CaseSource


class SignalLogEntry(BaseModel):
    """The base DTO for signals_log. Every field is known up front (there's
    no server-generated column on this table), so unlike Case/CaseEvent
    there's no "pre-persistence" state to represent."""

    model_config = ConfigDict(from_attributes=True)

    signal_id: str
    account_id: str
    device_context: str | None
    geo_context: str | None
    signal_type: str
    occurred_at: datetime
    source: CaseSource
    raw_signal: dict

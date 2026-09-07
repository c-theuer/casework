from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CaseEvent(BaseModel):
    """The base DTO for case_events. event_id/created_at are None for an
    event a service is about to log; CaseEventsRepository.log() populates
    them from the inserted row."""

    model_config = ConfigDict(from_attributes=True)

    event_id: UUID | None = None
    case_id: UUID
    event_type: str
    event_payload: dict = {}
    created_at: datetime | None = None

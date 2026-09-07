from typing import Protocol
from uuid import UUID

from app.domain.entities import CaseEvent


class CaseEventsRepository(Protocol):
    """Port for the append-only case_events audit log."""

    async def log(self, event: CaseEvent) -> CaseEvent: ...

    async def list_for_case(self, case_id: UUID) -> list[CaseEvent]: ...

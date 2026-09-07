from datetime import datetime
from typing import Protocol

from app.domain.entities import SignalLogEntry


class SignalsLogRepository(Protocol):
    """Port for the velocity log Triage's input is enriched from."""

    async def log(self, entry: SignalLogEntry) -> SignalLogEntry: ...

    async def count_recent(
        self,
        *,
        account_id: str | None = None,
        device_context: str | None = None,
        within_minutes: int = 10,
        now: datetime | None = None,
    ) -> int: ...

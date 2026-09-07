from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import SignalLogEntry
from app.domain.repositories import SignalsLogRepository
from app.infrastructure.db.models import SignalLog as SignalLogModel


class SqlAlchemySignalsLogRepository(SignalsLogRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def log(self, entry: SignalLogEntry) -> SignalLogEntry:
        """Idempotent on signal_id."""
        stmt = (
            insert(SignalLogModel)
            .values(**entry.model_dump())
            .on_conflict_do_nothing(index_elements=[SignalLogModel.signal_id])
        )
        await self._session.execute(stmt)
        await self._session.commit()
        row = await self._session.get(SignalLogModel, entry.signal_id)
        return SignalLogEntry.model_validate(row, from_attributes=True)

    async def count_recent(
        self,
        *,
        account_id: str | None = None,
        device_context: str | None = None,
        within_minutes: int = 10,
        now: datetime | None = None,
    ) -> int:
        """Velocity count used by Triage -- queried directly by the
        coordinator service via plain SQL, never exposed as an agent tool
        call."""
        if account_id is None and device_context is None:
            raise ValueError("must filter by account_id and/or device_context")
        cutoff = (now or datetime.now(UTC)) - timedelta(minutes=within_minutes)

        stmt = select(func.count()).select_from(SignalLogModel).where(SignalLogModel.occurred_at >= cutoff)
        if account_id is not None:
            stmt = stmt.where(SignalLogModel.account_id == account_id)
        if device_context is not None:
            stmt = stmt.where(SignalLogModel.device_context == device_context)

        result = await self._session.execute(stmt)
        return result.scalar_one()

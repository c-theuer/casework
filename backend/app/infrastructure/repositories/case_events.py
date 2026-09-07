from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import CaseEvent
from app.domain.repositories import CaseEventsRepository
from app.infrastructure.db.models import CaseEvent as CaseEventModel


class SqlAlchemyCaseEventsRepository(CaseEventsRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def log(self, event: CaseEvent) -> CaseEvent:
        # event_id/created_at excluded so the server_default fires instead
        # of binding an explicit NULL -- see SqlAlchemyCasesRepository.create().
        row = CaseEventModel(**event.model_dump(exclude={"event_id", "created_at"}))
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return CaseEvent.model_validate(row, from_attributes=True)

    async def list_for_case(self, case_id: UUID) -> list[CaseEvent]:
        stmt = (
            select(CaseEventModel)
            .where(CaseEventModel.case_id == case_id)
            .order_by(CaseEventModel.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [CaseEvent.model_validate(row, from_attributes=True) for row in result.scalars().all()]

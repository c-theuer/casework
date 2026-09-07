from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Persona
from app.domain.repositories import PersonasRepository
from app.infrastructure.db.models import Persona as PersonaModel


class SqlAlchemyPersonasRepository(PersonasRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_all(self) -> list[Persona]:
        result = await self._session.execute(select(PersonaModel).order_by(PersonaModel.account_id))
        return [Persona.model_validate(row, from_attributes=True) for row in result.scalars().all()]

    async def get(self, account_id: str) -> Persona | None:
        row = await self._session.get(PersonaModel, account_id)
        return Persona.model_validate(row, from_attributes=True) if row else None

    async def upsert(self, persona: Persona) -> Persona:
        values = persona.model_dump()
        stmt = insert(PersonaModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[PersonaModel.account_id],
            set_={k: v for k, v in values.items() if k != "account_id"},
        )
        await self._session.execute(stmt)
        await self._session.commit()
        row = await self._session.get(PersonaModel, persona.account_id)
        return Persona.model_validate(row, from_attributes=True)

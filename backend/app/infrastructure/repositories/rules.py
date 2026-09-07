from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Rule
from app.domain.repositories import RulesRepository
from app.infrastructure.db.models import Rule as RuleModel


class SqlAlchemyRulesRepository(RulesRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_active(self) -> list[Rule]:
        stmt = select(RuleModel).where(RuleModel.active).order_by(RuleModel.rule_id)
        result = await self._session.execute(stmt)
        return [Rule.model_validate(row, from_attributes=True) for row in result.scalars().all()]

    async def upsert(self, rule: Rule) -> Rule:
        values = rule.model_dump()
        stmt = insert(RuleModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[RuleModel.rule_id],
            set_={k: v for k, v in values.items() if k != "rule_id"},
        )
        await self._session.execute(stmt)
        await self._session.commit()
        row = await self._session.get(RuleModel, rule.rule_id)
        return Rule.model_validate(row, from_attributes=True)

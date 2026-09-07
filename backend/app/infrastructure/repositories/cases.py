from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Case, CaseStatus, Resolution
from app.domain.repositories import CasesRepository
from app.infrastructure.db.models import Case as CaseModel


class SqlAlchemyCasesRepository(CasesRepository):
    """Concrete adapter for the CasesRepository port. The base DTO
    (app.domain.entities.Case) is what every method takes and returns --
    app.infrastructure.db.models.Case (the SQLAlchemy model) never leaves
    this file. Callers (domain services) depend on the CasesRepository
    Protocol, never on this class directly."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, case: Case) -> Case:
        # case_id/created_at/updated_at are excluded, not just None, so they
        # stay unset on the transient row -- SQLAlchemy only lets the
        # column's server_default (gen_random_uuid()/now()) fire when a
        # mapped attribute was never touched at all; an explicit None would
        # bind a literal NULL and violate the NOT NULL constraints.
        row = CaseModel(**case.model_dump(exclude={"case_id", "created_at", "updated_at"}))
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return Case.model_validate(row, from_attributes=True)

    async def get(self, case_id: UUID) -> Case | None:
        row = await self._session.get(CaseModel, case_id)
        return Case.model_validate(row, from_attributes=True) if row else None

    async def list_pending(self, exclude_sources: tuple[str, ...] = ("eval",)) -> list[Case]:
        """Cases still awaiting a human decision. Includes both
        `pending_review` (elevated, full pipeline) and `auto_escalated`
        (critical, notified immediately) -- both still require one approval
        click before anything irreversible happens, and the demo app has a
        single queue view for both, per spec §9's "still requires one-click
        human approval" language for the critical path.

        Excludes `eval`-sourced cases by default (per spec §10's eval-harness
        idempotency requirement) but deliberately NOT `integration_test`:
        integration tests exercise this exact endpoint end to end and need
        their own fixture rows to actually show up in the response."""
        stmt = (
            select(CaseModel)
            .where(CaseModel.status.in_(["pending_review", "auto_escalated"]))
            .where(CaseModel.source.not_in(exclude_sources))
            .order_by(CaseModel.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [Case.model_validate(row, from_attributes=True) for row in result.scalars().all()]

    async def update_resolution(
        self, case_id: UUID, *, resolution: Resolution, status: CaseStatus, approved_by: str | None
    ) -> Case:
        row = await self._session.get(CaseModel, case_id)
        if row is None:
            # Callers are expected to have already confirmed the case exists
            # (CasesService does, via get()) -- this only fires on a race
            # (deleted between that check and this call), but the type
            # checker is right that session.get() can return None and this
            # must not silently AttributeError on the next line.
            raise LookupError(f"No case with id {case_id}")
        row.resolution = resolution.value
        row.status = status.value
        row.approved_by = approved_by
        await self._session.commit()
        await self._session.refresh(row)
        return Case.model_validate(row, from_attributes=True)

    async def find_similar(self, account_id: str, pattern: str | None, limit: int = 5) -> list[Case]:
        stmt = (
            select(CaseModel)
            .where(or_(CaseModel.account_id == account_id, CaseModel.pattern == pattern))
            .order_by(CaseModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [Case.model_validate(row, from_attributes=True) for row in result.scalars().all()]

    async def delete_by_source(self, source: str) -> None:
        await self._session.execute(delete(CaseModel).where(CaseModel.source == source))
        await self._session.commit()

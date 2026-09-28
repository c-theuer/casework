from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy import update as sa_update
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
        (critical, notified immediately), plus `error` cases left
        recoverable after a failed payment/capture step -- all still require
        an explicit human decision or retry path, and the demo app has a
        single queue view for them.

        Excludes `eval`-sourced cases by default (per spec §10's eval-harness
        idempotency requirement) but deliberately NOT `integration_test`:
        integration tests exercise this exact endpoint end to end and need
        their own fixture rows to actually show up in the response."""
        stmt = (
            select(CaseModel)
            .where(
                CaseModel.status.in_(
                    [
                        CaseStatus.PENDING_REVIEW.value,
                        CaseStatus.AUTO_ESCALATED.value,
                        CaseStatus.ERROR.value,
                    ]
                )
            )
            .where(CaseModel.source.not_in(exclude_sources))
            .order_by(CaseModel.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [Case.model_validate(row, from_attributes=True) for row in result.scalars().all()]

    async def update_resolution(
        self, case_id: UUID, *, resolution: Resolution, status: CaseStatus, approved_by: str | None
    ) -> Case | None:
        # Atomic conditional UPDATE, not a read-then-write: the WHERE clause
        # is the concurrency guard. Under READ COMMITTED, two concurrent
        # UPDATEs for the same case_id serialize on the row lock; the second
        # one to run re-evaluates this WHERE clause against the first one's
        # now-committed row, sees resolution is no longer 'none', and
        # correctly matches zero rows -- no explicit SELECT ... FOR UPDATE
        # needed. The status condition is what stops a low-route case
        # (status=closed, resolution=none, already auto-captured) from being
        # approved/denied a second time.
        stmt = (
            sa_update(CaseModel)
            .where(
                CaseModel.case_id == case_id,
                CaseModel.resolution == Resolution.NONE.value,
                CaseModel.status.in_(
                    [
                        CaseStatus.PENDING_REVIEW.value,
                        CaseStatus.AUTO_ESCALATED.value,
                        CaseStatus.ERROR.value,
                    ]
                ),
            )
            .values(resolution=resolution.value, status=status.value, approved_by=approved_by)
            .returning(CaseModel)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        await self._session.commit()
        return Case.model_validate(row, from_attributes=True) if row is not None else None

    async def update_status(
        self,
        case_id: UUID,
        *,
        current_statuses: tuple[CaseStatus, ...],
        new_status: CaseStatus,
        current_resolution: Resolution | None = None,
    ) -> Case | None:
        conditions = [
            CaseModel.case_id == case_id,
            CaseModel.status.in_([status.value for status in current_statuses]),
        ]
        if current_resolution is not None:
            conditions.append(CaseModel.resolution == current_resolution.value)
        stmt = (
            sa_update(CaseModel)
            .where(*conditions)
            .values(status=new_status.value)
            .returning(CaseModel)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        await self._session.commit()
        return Case.model_validate(row, from_attributes=True) if row is not None else None

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

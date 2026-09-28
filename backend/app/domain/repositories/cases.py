from typing import Protocol
from uuid import UUID

from app.domain.entities import Case, CaseStatus, Resolution


class CasesRepository(Protocol):
    """Port for persisting/querying the cases resource. Domain services
    (CoordinatorService, CasesService) depend on this abstraction only --
    never on the concrete SQLAlchemy adapter in
    app.infrastructure.repositories.cases."""

    async def create(self, case: Case) -> Case: ...

    async def get(self, case_id: UUID) -> Case | None: ...

    async def list_pending(self, exclude_sources: tuple[str, ...] = ("eval",)) -> list[Case]: ...

    async def update_resolution(
        self, case_id: UUID, *, resolution: Resolution, status: CaseStatus, approved_by: str | None
    ) -> Case | None:
        """Atomically transitions the case from resolution=NONE and a
        reviewable status to the given resolution -- an UPDATE ... WHERE ...
        RETURNING, not a read-then-write, so two concurrent calls for the
        same case can never both succeed. Returns None if the case didn't
        match (already resolved, or not in a reviewable status, e.g. a
        low-route case the pipeline already closed on its own); the caller
        does a follow-up get() only to classify that failure, never to gate
        the write itself."""
        ...

    async def update_status(
        self,
        case_id: UUID,
        *,
        current_statuses: tuple[CaseStatus, ...],
        new_status: CaseStatus,
        current_resolution: Resolution | None = None,
    ) -> Case | None:
        """Atomically changes status when the row still matches the expected
        status (and optionally resolution). Used for recoverable handoffs,
        e.g. marking a low-route capture failure as ERROR or closing a case
        only after its payment side effect succeeded."""
        ...

    async def find_similar(self, account_id: str, pattern: str | None, limit: int = 5) -> list[Case]: ...

    async def delete_by_source(self, source: str) -> None: ...

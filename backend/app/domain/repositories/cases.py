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
    ) -> Case: ...

    async def find_similar(self, account_id: str, pattern: str | None, limit: int = 5) -> list[Case]: ...

    async def delete_by_source(self, source: str) -> None: ...

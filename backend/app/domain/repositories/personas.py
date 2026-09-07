from typing import Protocol

from app.domain.entities import Persona


class PersonasRepository(Protocol):
    """Port for the seeded synthetic-customer personas table."""

    async def list_all(self) -> list[Persona]: ...

    async def get(self, account_id: str) -> Persona | None: ...

    async def upsert(self, persona: Persona) -> Persona: ...

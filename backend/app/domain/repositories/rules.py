from typing import Protocol

from app.domain.entities import Rule


class RulesRepository(Protocol):
    """Port for the rules table Research Agent matches against."""

    async def list_active(self) -> list[Rule]: ...

    async def upsert(self, rule: Rule) -> Rule: ...

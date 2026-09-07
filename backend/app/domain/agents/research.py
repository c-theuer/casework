from typing import Protocol

from app.domain.entities import ResearchBrief, TriageResult


class ResearchAgent(Protocol):
    """Port for the Research Agent (spec §3.02): pulls matched rules,
    similar past cases, and evidence for a triaged signal. Phase 2's
    adapter is scoped to a Postgres-only MCP server; Phase 1's is a static
    stub -- both satisfy this same port."""

    async def run(self, triage: TriageResult) -> ResearchBrief: ...

from app.domain.agents import ResearchAgent
from app.domain.entities import ResearchBrief, TriageResult


class StubResearchAgent(ResearchAgent):
    """Phase 1 adapter. Phase 2 adds a new adapter implementing the same
    ResearchAgent port, scoped to a Postgres-only MCP server, querying
    `rules` and `cases`."""

    async def run(self, triage: TriageResult) -> ResearchBrief:
        return ResearchBrief(
            signal_id=triage.signal_id,
            matched_rules=[],
            similar_cases=[],
            evidence=["stub: Research Agent not yet wired to Postgres MCP"],
        )

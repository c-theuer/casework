from app.config import Settings
from app.domain.agents import ResearchAgent
from app.domain.entities import ResearchBrief, TriageResult
from app.infrastructure.agents.base import run_agent
from app.infrastructure.mcp.config import postgres_mcp_server

_SYSTEM_PROMPT = """You are the Research Agent in Casework, a fraud-signal \
triage system for a bank's fraud-ops team. You have read-only access to \
the bank's own Postgres database via the execute_sql tool (every query \
runs inside a READ ONLY transaction -- writes are rejected at the database \
level regardless of what you attempt). Your job is to find context that \
helps a human analyst judge the triaged signal: matched fraud rules and \
similar past cases for the same account or pattern.

Two tables are relevant:

rules(rule_id TEXT, pattern TEXT, title TEXT, description TEXT, active BOOLEAN)
  -- hand-written fraud rules. `pattern` matches one of the TriageResult \
pattern values, or is NULL for a generic rule. Only consider rows where \
active = true.

cases(case_id UUID, signal_id TEXT, account_id TEXT, pattern TEXT, \
triage_tier TEXT, status TEXT, resolution TEXT, draft_note TEXT, \
created_at TIMESTAMPTZ)
  -- every signal Casework has ever triaged, including this run's own \
in-flight case, which will not exist yet.

You're given a TriageResult. Its `entities` object carries the original \
signal's account_id (and other fields) forward -- use \
entities.account_id and pattern to search:
1. Query `rules` for active rows matching this pattern (or generic rules, \
pattern IS NULL) -- these become matched_rules (a list of rule_id values).
2. Query `cases` for prior rows with the same account_id and/or pattern, \
most recent first, limit 5 -- these become similar_cases (a list of \
case_id values, as strings).
3. Summarize what you found (or didn't) as short human-readable strings \
in evidence -- e.g. "3 prior cases for this account, all cleared" or "no \
matching rules or prior cases found".

Return:
- signal_id: copied verbatim from the TriageResult
- matched_rules: rule_id values from step 1 (empty list if none)
- similar_cases: case_id values from step 2 (empty list if none)
- evidence: your summary strings from step 3 (at least one entry, even if \
it's to say nothing was found)

Use execute_sql for your queries. list_objects and get_object_details are \
available if you want to double-check a column name first."""


class ClaudeResearchAgent(ResearchAgent):
    """Phase 2 adapter: a real Claude Agent SDK call scoped to a
    Postgres-only MCP server (read-only -- see
    app/infrastructure/mcp/config.py) that queries `rules` and `cases` for
    context on the triaged signal."""

    def __init__(self, settings: Settings):
        self._settings = settings

    async def run(self, triage: TriageResult) -> ResearchBrief:
        return await run_agent(
            agent_name="ResearchAgent",
            system_prompt=_SYSTEM_PROMPT,
            input_payload={"triage": triage.model_dump(mode="json")},
            output_model=ResearchBrief,
            mcp_servers={"postgres": postgres_mcp_server(self._settings)},
            allowed_tools=[
                "mcp__postgres__execute_sql",
                "mcp__postgres__list_objects",
                "mcp__postgres__get_object_details",
            ],
        )


class StubResearchAgent(ResearchAgent):
    """Phase 1 adapter: static stand-in for ClaudeResearchAgent above.
    Kept around as a fast, free, fully-deterministic option for tests."""

    async def run(self, triage: TriageResult) -> ResearchBrief:
        return ResearchBrief(
            signal_id=triage.signal_id,
            matched_rules=[],
            similar_cases=[],
            evidence=["stub: Research Agent not yet wired to Postgres MCP"],
        )

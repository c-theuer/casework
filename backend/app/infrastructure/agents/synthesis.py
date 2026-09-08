from app.domain.agents import SynthesisAgent
from app.domain.entities import CaseRecommendation, ResearchBrief, TriageResult
from app.infrastructure.agents.base import run_agent

_ACTION_BY_TIER = {
    "critical": "block",
    "elevated": "flag_for_review",
    "low": "clear",
}

_SYSTEM_PROMPT = """You are the Synthesis Agent in Casework, a fraud-signal \
triage system for a bank's fraud-ops team. You receive a TriageResult (the \
classified pattern and tier) and a ResearchBrief (matched rules, similar \
past cases, and evidence pulled from the bank's own records). Your job is \
to produce a risk score, a recommended action, and a short drafted case \
note for the human analyst who will review this next.

Return:
- signal_id: copied verbatim from the TriageResult
- risk_score: 0.0 (no risk) to 1.0 (certain fraud), synthesizing the \
triage confidence and the strength of the research evidence -- evidence \
that corroborates the triaged pattern should raise the score, and an \
empty or contradicting research brief should lower your confidence \
relative to triage alone
- recommended_action: one of block, flag_for_review, monitor, clear
- draft_note: 2-4 sentences a fraud-ops analyst would read first -- state \
the pattern, why it was flagged, and what the research turned up (or that \
nothing relevant was found)
- requires_human_approval: always true. No recommendation in Casework is \
ever auto-executed -- a human always clicks approve or deny before \
anything happens against a real system.

You have no tools. Reason only over the TriageResult and ResearchBrief \
given to you."""


class ClaudeSynthesisAgent(SynthesisAgent):
    """Phase 2 adapter: a real Claude Agent SDK call, no MCP tools, no
    built-in tools -- reasons only over TriageResult + ResearchBrief."""

    async def run(self, triage: TriageResult, research: ResearchBrief) -> CaseRecommendation:
        return await run_agent(
            agent_name="SynthesisAgent",
            system_prompt=_SYSTEM_PROMPT,
            input_payload={
                "triage": triage.model_dump(mode="json"),
                "research": research.model_dump(mode="json"),
            },
            output_model=CaseRecommendation,
        )


class StubSynthesisAgent(SynthesisAgent):
    """Phase 1 adapter: deterministic heuristic standing in for
    ClaudeSynthesisAgent above. Kept around as a fast, free, fully-
    deterministic option for tests."""

    async def run(self, triage: TriageResult, research: ResearchBrief) -> CaseRecommendation:
        action = _ACTION_BY_TIER[triage.tier]
        note = (
            f"[stub draft] Signal {triage.signal_id}: pattern={triage.pattern}, "
            f"confidence={triage.confidence:.2f}. {len(research.evidence)} evidence item(s) reviewed."
        )
        return CaseRecommendation(
            signal_id=triage.signal_id,
            risk_score=triage.confidence,
            recommended_action=action,
            draft_note=note,
            requires_human_approval=True,
        )

from app.domain.agents import SynthesisAgent
from app.domain.entities import CaseRecommendation, ResearchBrief, TriageResult

_ACTION_BY_TIER = {
    "critical": "block",
    "elevated": "flag_for_review",
    "low": "clear",
}


class StubSynthesisAgent(SynthesisAgent):
    """Phase 1 adapter. Phase 2 adds a new adapter implementing the same
    SynthesisAgent port (no MCP tools) reasoning over TriageResult +
    ResearchBrief via a real Claude Agent SDK call."""

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

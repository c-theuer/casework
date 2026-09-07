import pytest

from app.domain.entities import ResearchBrief, TriageResult
from app.infrastructure.agents import StubSynthesisAgent


def make_triage(tier: str) -> TriageResult:
    return TriageResult(signal_id="sig_1", pattern="merchant_fraud", tier=tier, confidence=0.6, entities={})


@pytest.mark.asyncio
class TestStubSynthesisAgent:
    async def test_critical_tier_recommends_block(self):
        research = ResearchBrief(signal_id="sig_1", matched_rules=[], similar_cases=[], evidence=[])
        result = await StubSynthesisAgent().run(make_triage("critical"), research)
        assert result.recommended_action == "block"
        assert result.requires_human_approval is True

    async def test_elevated_tier_recommends_flag_for_review(self):
        research = ResearchBrief(signal_id="sig_1", matched_rules=[], similar_cases=[], evidence=[])
        result = await StubSynthesisAgent().run(make_triage("elevated"), research)
        assert result.recommended_action == "flag_for_review"

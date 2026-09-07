from typing import Protocol

from app.domain.entities import CaseRecommendation, ResearchBrief, TriageResult


class SynthesisAgent(Protocol):
    """Port for the Synthesis Agent (spec §3.03): produces a risk score,
    recommended action, and drafted case note from Triage + Research
    output."""

    async def run(self, triage: TriageResult, research: ResearchBrief) -> CaseRecommendation: ...

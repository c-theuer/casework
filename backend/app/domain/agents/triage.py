from typing import Protocol

from app.domain.entities import Signal, TriageResult


class TriageAgent(Protocol):
    """Port for the Triage Agent (spec §3.01): classifies a Signal into a
    fraud pattern + risk tier. Phase 1's concrete adapter
    (app.infrastructure.agents.triage.TriageService) is a deterministic
    heuristic; Phase 2 swaps in a Claude Agent SDK-backed adapter behind
    this exact same port -- CoordinatorService never changes."""

    async def run(self, signal: Signal, velocity_context: dict) -> TriageResult: ...

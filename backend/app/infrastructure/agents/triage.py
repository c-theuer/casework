from app.domain.agents import TriageAgent
from app.domain.entities import Signal, TriageResult


class StubTriageAgent(TriageAgent):
    """Phase 1 adapter: deterministic heuristic standing in for the real
    Claude Agent SDK call (Phase 2). No MCP tools -- reasons only over the
    Signal plus a velocity_context dict the coordinator computed from
    signals_log. Phase 2 adds a new adapter implementing the same
    TriageAgent port; CoordinatorService doesn't change."""

    async def run(self, signal: Signal, velocity_context: dict) -> TriageResult:
        entities = {
            "account_id": signal.account_id,
            "merchant_id": signal.payload.get("merchant_id"),
            "device_context": signal.payload.get("device_context"),
            "geo_context": signal.payload.get("geo_context"),
            "amount": signal.payload.get("amount"),
            **velocity_context,
        }
        confidence = min(max(signal.upstream_score, 0.0), 1.0)

        if confidence < 0.4:
            pattern, tier = "benign", "low"
        elif confidence > 0.85:
            pattern = "card_testing" if "velocity" in signal.flag_reason else "account_takeover"
            tier = "critical"
        else:
            pattern, tier = "merchant_fraud", "elevated"

        return TriageResult(
            signal_id=signal.signal_id,
            pattern=pattern,
            tier=tier,
            confidence=confidence,
            entities=entities,
        )

from app.domain.agents import TriageAgent
from app.domain.entities import Signal, TriageResult
from app.infrastructure.agents.base import run_agent

_SYSTEM_PROMPT = """You are the Triage Agent in Casework, a fraud-signal \
triage system for a bank's fraud-ops team. An upstream real-time scoring \
layer (rules + ML, sub-100ms, running on 100% of transactions) has already \
flagged this Signal for human-speed review -- your job is to classify it, \
not to re-score it from scratch.

Classify the Signal into exactly one fraud pattern:
- card_testing: rapid small-value authorization attempts across a card range
- account_takeover: new device and/or new location, often paired with a \
password reset or failed logins, followed by high-value activity
- merchant_fraud: chargeback-rate spike concentrated at one merchant
- mule_activity: rapid in-and-out transfers across newly linked accounts
- friendly_fraud: a chargeback/dispute with a prior legitimate purchase \
history at the same merchant
- benign: no matched fraud pattern

Assign a tier reflecting how urgent this looks: critical, elevated, or low.

Return:
- signal_id: copied verbatim from the input Signal
- pattern: one of the six patterns above
- tier: one of critical/elevated/low
- confidence: your confidence in the pattern classification, 0.0 to 1.0
- entities: a JSON object. Copy account_id, merchant_id, device_context, \
geo_context, and amount from the Signal's payload verbatim -- never invent \
or alter these values. Also copy every key from the supplied \
velocity_context object into entities unchanged. These fields are the only \
channel later agents have back to the original Signal, so accuracy here \
matters more than completeness elsewhere.

You have no tools. Reason only over the Signal and velocity_context given \
to you."""


class ClaudeTriageAgent(TriageAgent):
    """Phase 2 adapter: a real Claude Agent SDK call, no MCP tools, no
    built-in tools -- reasons only over the Signal plus the velocity_context
    dict the coordinator computed from signals_log."""

    async def run(self, signal: Signal, velocity_context: dict) -> TriageResult:
        return await run_agent(
            agent_name="TriageAgent",
            system_prompt=_SYSTEM_PROMPT,
            input_payload={
                "signal": signal.model_dump(mode="json"),
                "velocity_context": velocity_context,
            },
            output_model=TriageResult,
        )


class StubTriageAgent(TriageAgent):
    """Phase 1 adapter: deterministic heuristic standing in for
    ClaudeTriageAgent above. No MCP tools -- reasons only over the Signal
    plus a velocity_context dict the coordinator computed from signals_log.
    Kept around as a fast, free, fully-deterministic option for tests."""

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

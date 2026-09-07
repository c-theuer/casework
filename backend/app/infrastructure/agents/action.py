from datetime import UTC, datetime

from app.domain.agents import ActionAgent
from app.domain.entities import ActionResult, Case


class StubActionAgent(ActionAgent):
    """Phase 1 adapter. Phase 2 adds a new adapter implementing the same
    ActionAgent port, split into two real modes:
    - notify(): Slack-only MCP tools, fired on the critical path pre-approval.
    - execute(): Stripe+Slack+GitHub MCP tools, fired only from POST /cases/{id}/approve.
    Never given both at once in the same call -- see plan's MCP scoping table.
    """

    async def notify(self, case: Case) -> ActionResult:
        return ActionResult(
            signal_id=case.signal_id,
            action_taken="notify_fraud_ops (stub, no real Slack call yet)",
            executed_by="casework-action-agent",
            approved_by="",
            timestamp=datetime.now(UTC),
        )

    async def execute(self, case: Case, approved_by: str) -> ActionResult:
        return ActionResult(
            signal_id=case.signal_id,
            action_taken=f"executed:{case.recommended_action} (stub, no real Stripe/Slack/GitHub calls yet)",
            executed_by="casework-action-agent",
            approved_by=approved_by,
            timestamp=datetime.now(UTC),
        )

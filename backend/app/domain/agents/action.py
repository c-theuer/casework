from typing import Protocol

from app.domain.entities import ActionResult, Case


class ActionAgent(Protocol):
    """Port for the Action Agent (spec §3.04): the only agent that touches
    real external systems. notify() is Slack-only (fired pre-approval on
    the critical path); execute() is Stripe+Slack+GitHub (fired only after
    a human approves) -- Phase 2's adapter enforces that split via which
    MCP servers each method is allowed to reach, never both at once."""

    async def notify(self, case: Case) -> ActionResult: ...

    async def execute(self, case: Case, approved_by: str) -> ActionResult: ...

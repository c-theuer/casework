from typing import Protocol

from app.domain.entities import ActionResult, Case


class ActionAgent(Protocol):
    """Port for the Action Agent (spec §3.04): the only agent that touches
    real external systems. notify() is Slack-only (fired pre-approval on
    the critical path); execute() is Slack+GitHub (fired only after a
    human approves). Neither ever touches Stripe -- capturing or
    cancelling the held PaymentIntent is a deterministic decision made by
    CasesService, not something delegated to an LLM."""

    async def notify(self, case: Case) -> ActionResult: ...

    async def execute(self, case: Case, approved_by: str) -> ActionResult: ...

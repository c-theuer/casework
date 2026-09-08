import json
from datetime import UTC, datetime

from app.config import Settings
from app.domain.agents import ActionAgent
from app.domain.entities import ActionResult, Case
from app.infrastructure.agents.base import run_agent_freeform
from app.infrastructure.mcp.config import github_mcp_server, slack_mcp_server

_NOTIFY_SYSTEM_PROMPT = """You are the Action Agent in Casework, a \
fraud-signal triage system for a bank's fraud-ops team. This case was just \
auto-escalated to critical tier -- your one job right now is to post the \
human-approval prompt to the fraud-ops Slack channel. Nothing irreversible \
happens until a human clicks Approve or Deny in the fraud-ops queue web \
app; this message is what tells them a case is waiting.

The channel below is given by name, not ID. First call slack_list_channels \
and find the channel whose name matches (ignoring a leading '#'), then use \
its id for slack_post_message -- posting requires a channel_id, a name is \
not accepted. If no channel matches, stop and say so instead of guessing \
an id.

Post exactly one message to the matched channel. Include: the account, the \
triaged pattern, the drafted case note, the recommended action, and a \
line telling the analyst to approve or deny it from the fraud-ops queue. \
Then briefly confirm what you posted."""

_EXECUTE_SYSTEM_PROMPT = """You are the Action Agent in Casework, a \
fraud-signal triage system for a bank's fraud-ops team. A human analyst \
has just approved this case's recommendation -- your job is to log that \
decision against real systems. This only ever runs after that human \
approval; never take these actions speculatively or repeat them.

Payments are never your concern: Casework never captures a transaction \
before this pipeline runs, so approving/denying a case only ever captures \
or cancels an already-held authorization, and that capture/cancel call is \
made deterministically in code before you're ever invoked -- {payment_note} \
Do not attempt any Stripe action yourself; there is no Stripe tool \
available to you.

Always do both of the following:
1. Post a short summary to the given Slack channel: the account, the \
pattern, the recommended action, who approved it, and the payment outcome \
noted above. The channel is given by name, not ID -- first call \
slack_list_channels and find the channel whose name matches (ignoring a \
leading '#'), then use its id for slack_post_message. If no channel \
matches, skip the Slack post and say so in your final summary rather than \
guessing an id.
2. File a GitHub issue in the given repository: a title naming the \
account and pattern, a body with the full case details, approver, and \
payment outcome, labeled with the case's tier.

Once finished, briefly confirm what you did."""

_PAYMENT_NOTE_BLOCK = "the held PaymentIntent {payment_intent_id} was cancelled, no charge will ever complete."
_PAYMENT_NOTE_ALLOW = "the held PaymentIntent {payment_intent_id} was captured, the charge is now final."
_PAYMENT_NOTE_NONE = "this case has no real PaymentIntent attached (synthetic/eval data), nothing to report."


class ClaudeActionAgent(ActionAgent):
    """Phase 2 adapter: real Claude Agent SDK calls, split into two modes
    with strictly different MCP scopes so neither can reach what the other
    can:
    - notify(): Slack-only, fired automatically pre-approval on the
      critical path.
    - execute(): Slack + GitHub, fired only after a human approves. Never
      touches Stripe -- capture/cancel is a deterministic decision made in
      app.domain.services.cases_service.CasesService before execute() is
      even called, not something an LLM decides or performs.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    async def notify(self, case: Case) -> ActionResult:
        prompt = (
            f"Channel: {self._settings.slack_fraud_ops_channel}\n\n"
            f"Case:\n{json.dumps(case.model_dump(mode='json'), default=str)}"
        )
        raw_text = await run_agent_freeform(
            agent_name="ActionAgent.notify",
            system_prompt=_NOTIFY_SYSTEM_PROMPT,
            prompt=prompt,
            mcp_servers={"slack": slack_mcp_server(self._settings)},
            allowed_tools=[
                "mcp__slack__slack_list_channels",
                "mcp__slack__slack_post_message",
            ],
        )
        return ActionResult(
            signal_id=case.signal_id,
            action_taken=f"notify_fraud_ops: {raw_text.strip()[:500]}",
            executed_by="casework-action-agent",
            approved_by="",
            timestamp=datetime.now(UTC),
        )

    async def execute(self, case: Case, approved_by: str) -> ActionResult:
        # execute() only ever runs from CasesService.approve(), which has
        # already resolved the payment by the time this is called: a
        # "block" recommendation means it was just cancelled, anything else
        # means it was just captured. See _should_cancel in cases_service.py
        # -- this is purely informational text for the agent's summary, not
        # a decision made here.
        if not case.stripe_payment_intent_id:
            payment_note = _PAYMENT_NOTE_NONE
        elif case.recommended_action == "block":
            payment_note = _PAYMENT_NOTE_BLOCK.format(payment_intent_id=case.stripe_payment_intent_id)
        else:
            payment_note = _PAYMENT_NOTE_ALLOW.format(payment_intent_id=case.stripe_payment_intent_id)

        system_prompt = _EXECUTE_SYSTEM_PROMPT.format(payment_note=payment_note)
        prompt = (
            f"Channel: {self._settings.slack_fraud_ops_channel}\n"
            f"GitHub repo: {self._settings.github_demo_repo}\n"
            f"Approved by: {approved_by}\n\n"
            f"Case:\n{json.dumps(case.model_dump(mode='json'), default=str)}"
        )
        raw_text = await run_agent_freeform(
            agent_name="ActionAgent.execute",
            system_prompt=system_prompt,
            prompt=prompt,
            mcp_servers={
                "slack": slack_mcp_server(self._settings),
                "github": github_mcp_server(self._settings),
            },
            allowed_tools=[
                "mcp__slack__slack_list_channels",
                "mcp__slack__slack_post_message",
                "mcp__github__create_issue",
            ],
        )
        return ActionResult(
            signal_id=case.signal_id,
            action_taken=f"executed:{case.recommended_action}: {raw_text.strip()[:500]}",
            executed_by="casework-action-agent",
            approved_by=approved_by,
            timestamp=datetime.now(UTC),
        )


class StubActionAgent(ActionAgent):
    """Phase 1 adapter: static stand-in for ClaudeActionAgent above. Kept
    around as a fast, free, fully-deterministic option for tests."""

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
            action_taken=f"executed:{case.recommended_action} (stub, no real Slack/GitHub calls yet)",
            executed_by="casework-action-agent",
            approved_by=approved_by,
            timestamp=datetime.now(UTC),
        )

"""These tests exist to pin down the actual security boundary: which MCP
servers/tools each real agent adapter is allowed to reach. Mocks the shared
run_agent()/run_agent_freeform() helper rather than the SDK's query()
directly, since what matters here is what each adapter *asks for*, not the
JSON-parsing machinery already covered in test_base.py."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.config import Settings
from app.domain.entities import (
    ActionResult,
    Case,
    CaseRecommendation,
    CaseStatus,
    ResearchBrief,
    Signal,
    TriageResult,
)
from app.infrastructure.agents.action import ClaudeActionAgent
from app.infrastructure.agents.research import ClaudeResearchAgent
from app.infrastructure.agents.synthesis import ClaudeSynthesisAgent
from app.infrastructure.agents.triage import ClaudeTriageAgent


def make_settings(**overrides) -> Settings:
    defaults = dict(
        anthropic_api_key="ak_test",
        stripe_secret_key="sk_test",
        slack_bot_token="xoxb_test",
        slack_fraud_ops_channel="#fraud-ops",
        github_pat="ghp_test",
        github_demo_repo="acme/casework-demo",
        database_url="postgresql://x:x@localhost/x",
    )
    defaults.update(overrides)
    return Settings.model_validate(defaults)


def make_case(**overrides) -> Case:
    now = datetime.now(UTC)
    defaults = dict(
        case_id=uuid4(),
        signal_id="sig_1",
        account_id="acct_1",
        signal_type="transaction",
        occurred_at=now,
        upstream_score=0.9,
        flag_reason="stripe_radar_highest",
        payload={},
        status=CaseStatus.AUTO_ESCALATED,
        source="live_stripe",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Case(**defaults)


@pytest.mark.asyncio
class TestClaudeTriageAgentScoping:
    async def test_no_mcp_servers_or_tools(self):
        with patch(
            "app.infrastructure.agents.triage.run_agent",
            new=AsyncMock(return_value=TriageResult(signal_id="s", pattern="benign", tier="low", confidence=0.1, entities={})),
        ) as mock_run:
            await ClaudeTriageAgent().run(
                Signal(
                    signal_id="s",
                    signal_type="transaction",
                    occurred_at=datetime.now(UTC),
                    account_id="a",
                    upstream_score=0.1,
                    flag_reason="x",
                    payload={},
                ),
                velocity_context={},
            )
        _, kwargs = mock_run.call_args
        assert kwargs.get("mcp_servers") is None
        assert kwargs.get("allowed_tools") is None


@pytest.mark.asyncio
class TestClaudeSynthesisAgentScoping:
    async def test_no_mcp_servers_or_tools(self):
        with patch(
            "app.infrastructure.agents.synthesis.run_agent",
            new=AsyncMock(
                return_value=CaseRecommendation(
                    signal_id="s", risk_score=0.5, recommended_action="clear",
                    draft_note="n", requires_human_approval=True,
                )
            ),
        ) as mock_run:
            triage = TriageResult(signal_id="s", pattern="benign", tier="low", confidence=0.1, entities={})
            research = ResearchBrief(signal_id="s", matched_rules=[], similar_cases=[], evidence=[])
            await ClaudeSynthesisAgent().run(triage, research)
        _, kwargs = mock_run.call_args
        assert kwargs.get("mcp_servers") is None
        assert kwargs.get("allowed_tools") is None


@pytest.mark.asyncio
class TestClaudeResearchAgentScoping:
    async def test_only_postgres_mcp_server_and_read_only_tools(self):
        with patch(
            "app.infrastructure.agents.research.run_agent",
            new=AsyncMock(
                return_value=ResearchBrief(signal_id="s", matched_rules=[], similar_cases=[], evidence=[])
            ),
        ) as mock_run:
            triage = TriageResult(signal_id="s", pattern="benign", tier="low", confidence=0.1, entities={})
            await ClaudeResearchAgent(make_settings()).run(triage)
        _, kwargs = mock_run.call_args
        assert set(kwargs["mcp_servers"].keys()) == {"postgres"}
        assert all(tool.startswith("mcp__postgres__") for tool in kwargs["allowed_tools"])


@pytest.mark.asyncio
class TestClaudeActionAgentScoping:
    async def test_notify_only_reaches_slack(self):
        with patch(
            "app.infrastructure.agents.action.run_agent_freeform",
            new=AsyncMock(return_value="posted"),
        ) as mock_run:
            await ClaudeActionAgent(make_settings()).notify(make_case())
        _, kwargs = mock_run.call_args
        assert set(kwargs["mcp_servers"].keys()) == {"slack"}
        assert all(tool.startswith("mcp__slack__") for tool in kwargs["allowed_tools"])

    async def test_execute_never_reaches_stripe_regardless_of_recommendation(self):
        """Capturing/cancelling the held PaymentIntent is a deterministic
        decision made by CasesService before execute() is ever called --
        the Action Agent has no Stripe tool available to it at all, whether
        or not this case has a real payment attached."""
        for case in (
            make_case(recommended_action="flag_for_review", stripe_payment_intent_id=None),
            make_case(recommended_action="block", stripe_payment_intent_id="pi_123"),
        ):
            with patch(
                "app.infrastructure.agents.action.run_agent_freeform",
                new=AsyncMock(return_value="done"),
            ) as mock_run:
                await ClaudeActionAgent(make_settings()).execute(case, approved_by="analyst_1")
            _, kwargs = mock_run.call_args
            assert set(kwargs["mcp_servers"].keys()) == {"slack", "github"}
            assert not any("stripe" in tool for tool in kwargs["allowed_tools"])

    async def test_action_result_fields_are_code_generated_not_agent_generated(self):
        """timestamp/executed_by shouldn't depend on the LLM producing a
        valid ISO datetime -- they're set deterministically after the tool
        call, per the design note in action.py."""
        with patch(
            "app.infrastructure.agents.action.run_agent_freeform",
            new=AsyncMock(return_value="posted the alert"),
        ):
            result: ActionResult = await ClaudeActionAgent(make_settings()).notify(make_case())
        assert result.executed_by == "casework-action-agent"
        assert result.approved_by == ""
        assert "posted the alert" in result.action_taken

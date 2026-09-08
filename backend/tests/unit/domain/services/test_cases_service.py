from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.entities import ActionResult, Case, CaseSource, CaseStatus, Resolution
from app.domain.services import CaseAlreadyResolvedError, CaseNotFoundError, CasesService
from app.infrastructure.payments.stub_gateway import StubPaymentGateway


def make_case_dto(**overrides) -> Case:
    now = datetime.now(UTC)
    defaults = dict(
        case_id=uuid4(),
        signal_id="sig_1",
        account_id="acct_1",
        signal_type="transaction",
        occurred_at=now,
        upstream_score=0.6,
        flag_reason="ml_score_0.60",
        payload={},
        status=CaseStatus.PENDING_REVIEW,
        resolution=Resolution.NONE,
        source=CaseSource.LIVE_STRIPE,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Case(**defaults)


def make_service():
    cases_repo = AsyncMock()
    case_events_repo = AsyncMock()
    action_agent = AsyncMock()
    # StubPaymentGateway is a real, deterministic collaborator here (not a
    # mock) -- it records every payment_intent_id passed to capture()/
    # cancel() in order, so tests can assert on which resolution actually
    # happened instead of just that *some* method was called.
    payment_gateway = StubPaymentGateway()
    return (
        CasesService(cases_repo, case_events_repo, action_agent, payment_gateway),
        cases_repo,
        case_events_repo,
        action_agent,
        payment_gateway,
    )


@pytest.mark.asyncio
class TestCasesService:
    async def test_approve_executes_action_and_persists_resolution(self):
        service, cases_repo, _case_events_repo, action_agent, _payment_gateway = make_service()
        case_id = uuid4()
        cases_repo.get.return_value = make_case_dto(case_id=case_id)
        cases_repo.update_resolution.return_value = make_case_dto(
            case_id=case_id, status=CaseStatus.CLOSED, resolution=Resolution.APPROVED, approved_by="analyst_1"
        )
        action_agent.execute.return_value = ActionResult(
            signal_id="sig_1",
            action_taken="executed:block",
            executed_by="casework-action-agent",
            approved_by="analyst_1",
            timestamp=datetime.now(UTC),
        )

        await service.approve(case_id, "analyst_1")

        action_agent.execute.assert_awaited_once()
        cases_repo.update_resolution.assert_awaited_once_with(
            case_id, resolution=Resolution.APPROVED, status=CaseStatus.CLOSED, approved_by="analyst_1"
        )

    async def test_deny_does_not_call_action_agent(self):
        service, cases_repo, _case_events_repo, action_agent, _payment_gateway = make_service()
        case_id = uuid4()
        cases_repo.get.return_value = make_case_dto(case_id=case_id)
        cases_repo.update_resolution.return_value = make_case_dto(
            case_id=case_id, status=CaseStatus.CLOSED, resolution=Resolution.DENIED
        )

        await service.deny(case_id, "analyst_1")

        action_agent.execute.assert_not_called()
        cases_repo.update_resolution.assert_awaited_once_with(
            case_id, resolution=Resolution.DENIED, status=CaseStatus.CLOSED, approved_by=None
        )

    async def test_approve_unknown_case_raises_not_found(self):
        service, cases_repo, *_ = make_service()
        cases_repo.get.return_value = None

        with pytest.raises(CaseNotFoundError):
            await service.approve(uuid4(), "analyst_1")

    async def test_approve_already_resolved_case_raises(self):
        service, cases_repo, *_ = make_service()
        cases_repo.get.return_value = make_case_dto(resolution=Resolution.APPROVED)

        with pytest.raises(CaseAlreadyResolvedError):
            await service.approve(uuid4(), "analyst_1")

    async def test_list_pending_delegates_to_repository(self):
        service, cases_repo, *_ = make_service()
        rows = [make_case_dto(signal_id="sig_a"), make_case_dto(signal_id="sig_b")]
        cases_repo.list_pending.return_value = rows

        result = await service.list_pending()

        assert [c.signal_id for c in result] == ["sig_a", "sig_b"]

    async def test_approving_a_block_recommendation_cancels_the_payment(self):
        """Approving means agreeing with the recommendation -- if the agent
        recommended "block", the analyst agreeing means the held
        authorization must be cancelled, never captured."""
        service, cases_repo, _case_events_repo, action_agent, payment_gateway = make_service()
        case_id = uuid4()
        case = make_case_dto(case_id=case_id, recommended_action="block", stripe_payment_intent_id="pi_1")
        cases_repo.get.return_value = case
        cases_repo.update_resolution.return_value = case
        action_agent.execute.return_value = ActionResult(
            signal_id="sig_1", action_taken="x", executed_by="a", approved_by="analyst_1",
            timestamp=datetime.now(UTC),
        )

        await service.approve(case_id, "analyst_1")

        assert payment_gateway.cancelled == ["pi_1"]
        assert payment_gateway.captured == []

    async def test_approving_a_non_block_recommendation_captures_the_payment(self):
        service, cases_repo, _case_events_repo, action_agent, payment_gateway = make_service()
        case_id = uuid4()
        case = make_case_dto(case_id=case_id, recommended_action="flag_for_review", stripe_payment_intent_id="pi_1")
        cases_repo.get.return_value = case
        cases_repo.update_resolution.return_value = case
        action_agent.execute.return_value = ActionResult(
            signal_id="sig_1", action_taken="x", executed_by="a", approved_by="analyst_1",
            timestamp=datetime.now(UTC),
        )

        await service.approve(case_id, "analyst_1")

        assert payment_gateway.captured == ["pi_1"]
        assert payment_gateway.cancelled == []

    async def test_denying_a_block_recommendation_captures_the_payment(self):
        """Denying means overriding the recommendation -- if the agent
        recommended "block" and the analyst denies that, they think it's
        legitimate after all, so the authorization is captured, not
        cancelled."""
        service, cases_repo, _case_events_repo, _action_agent, payment_gateway = make_service()
        case_id = uuid4()
        case = make_case_dto(case_id=case_id, recommended_action="block", stripe_payment_intent_id="pi_1")
        cases_repo.get.return_value = case
        cases_repo.update_resolution.return_value = case

        await service.deny(case_id, "analyst_1")

        assert payment_gateway.captured == ["pi_1"]
        assert payment_gateway.cancelled == []

    async def test_denying_a_non_block_recommendation_cancels_the_payment(self):
        service, cases_repo, _case_events_repo, _action_agent, payment_gateway = make_service()
        case_id = uuid4()
        case = make_case_dto(case_id=case_id, recommended_action="clear", stripe_payment_intent_id="pi_1")
        cases_repo.get.return_value = case
        cases_repo.update_resolution.return_value = case

        await service.deny(case_id, "analyst_1")

        assert payment_gateway.cancelled == ["pi_1"]
        assert payment_gateway.captured == []

    async def test_approve_without_a_real_payment_intent_never_touches_the_gateway(self):
        """Synthetic/eval cases have no real PaymentIntent attached."""
        service, cases_repo, _case_events_repo, action_agent, payment_gateway = make_service()
        case_id = uuid4()
        case = make_case_dto(case_id=case_id, recommended_action="block", stripe_payment_intent_id=None)
        cases_repo.get.return_value = case
        cases_repo.update_resolution.return_value = case
        action_agent.execute.return_value = ActionResult(
            signal_id="sig_1", action_taken="x", executed_by="a", approved_by="analyst_1",
            timestamp=datetime.now(UTC),
        )

        await service.approve(case_id, "analyst_1")

        assert payment_gateway.captured == []
        assert payment_gateway.cancelled == []

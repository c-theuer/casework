from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.entities import CaseStatus, Resolution, Route
from app.domain.services import AuthorizationDeclinedError, CheckoutService, CoordinatorError
from app.infrastructure.payments.stub_gateway import StubPaymentGateway


def make_service(coordinator=None):
    coordinator = coordinator or AsyncMock()
    # StubPaymentGateway is a real, deterministic collaborator here (not a
    # mock) -- it's exactly as fast/free as mocking Stripe would be, but
    # exercises CheckoutService._authorize()'s actual translation of
    # PaymentDeclinedError -> AuthorizationDeclinedError instead of assuming it.
    payment_gateway = StubPaymentGateway()
    cases_repo = AsyncMock()
    return CheckoutService(coordinator, cases_repo, payment_gateway), coordinator, cases_repo, payment_gateway


@pytest.mark.asyncio
class TestCheckoutService:
    async def test_elevated_card_succeeds_and_creates_a_case(self):
        service, coordinator, _cases_repo, payment_gateway = make_service()
        coordinator.handle_signal.return_value.status = CaseStatus.PENDING_REVIEW

        result = await service.checkout(
            account_id="acct_1",
            amount=10.0,
            merchant_id="m1",
            device_context="known_device",
            geo_context="usual_location",
            recent_password_reset=False,
            mfa_completed=True,
            failed_logins_this_session=0,
            test_card="elevated",
        )

        assert result.risk_level == "elevated"
        assert result.case is not None
        assert result.pipeline_error is None
        coordinator.handle_signal.assert_awaited_once()
        # Not a low-route case (the mocked coordinator's return value isn't
        # Route.LOW) -- the authorization must stay held, not captured.
        assert payment_gateway.captured == []

    async def test_low_route_case_is_captured_immediately(self):
        """A low route means the pipeline itself is the approval -- nothing
        else ever reviews it, so the held authorization must be captured
        right away rather than left dangling."""
        service, coordinator, _cases_repo, payment_gateway = make_service()
        coordinator.handle_signal.return_value.status = CaseStatus.CLOSED
        coordinator.handle_signal.return_value.route = Route.LOW

        result = await service.checkout(
            account_id="acct_1",
            amount=10.0,
            merchant_id="m1",
            device_context="known_device",
            geo_context="usual_location",
            recent_password_reset=False,
            mfa_completed=True,
            failed_logins_this_session=0,
            test_card="elevated",
        )

        assert result.pipeline_error is None
        assert payment_gateway.captured == [result.payment_intent_id]

    async def test_highest_not_blocked_card_still_charges_and_creates_a_signal(self):
        service, coordinator, _cases_repo, payment_gateway = make_service()

        result = await service.checkout(
            account_id="acct_1",
            amount=999.0,
            merchant_id="m1",
            device_context="new_device",
            geo_context="new_or_foreign_location",
            recent_password_reset=False,
            mfa_completed=False,
            failed_logins_this_session=0,
            test_card="highest_not_blocked",
        )

        assert result.risk_level == "highest"
        coordinator.handle_signal.assert_awaited_once()
        assert payment_gateway.captured == []

    async def test_highest_blocked_card_raises_before_ever_calling_coordinator(self):
        service, coordinator, _cases_repo, payment_gateway = make_service()

        with pytest.raises(AuthorizationDeclinedError):
            await service.checkout(
                account_id="acct_1",
                amount=5.0,
                merchant_id="m1",
                device_context="new_device",
                geo_context="usual_location",
                recent_password_reset=False,
                mfa_completed=False,
                failed_logins_this_session=0,
                test_card="highest_blocked",
            )

        coordinator.handle_signal.assert_not_called()
        assert payment_gateway.captured == []

    async def test_pipeline_failure_with_no_case_created_cancels_the_dangling_authorization(self):
        """The auth path is independent of the investigation queue: a
        downstream pipeline failure must not take down the charge result --
        but with no case ever created, there's no human-review path this
        authorization could ever reach, so it must be actively cancelled
        rather than left dangling until Stripe's own 7-day auto-cancel."""
        service, coordinator, _cases_repo, payment_gateway = make_service()
        coordinator.handle_signal.side_effect = CoordinatorError("sig_1", "triage", RuntimeError("x"), case_id=None)

        result = await service.checkout(
            account_id="acct_1",
            amount=10.0,
            merchant_id="m1",
            device_context="known_device",
            geo_context="usual_location",
            recent_password_reset=False,
            mfa_completed=True,
            failed_logins_this_session=0,
            test_card="elevated",
        )

        assert result.risk_level == "elevated"
        assert result.case is None
        assert result.pipeline_error is not None
        assert "cancelled" in result.pipeline_error
        assert payment_gateway.captured == []
        assert payment_gateway.cancelled == [result.payment_intent_id]

    async def test_pipeline_failure_reports_clearly_when_cancelling_also_fails(self):
        """Never a raw exception/500 even in the double-failure case --
        still a 200 with a message flagging it for manual review."""
        coordinator = AsyncMock()
        cases_repo = AsyncMock()
        coordinator.handle_signal.side_effect = CoordinatorError("sig_1", "triage", RuntimeError("x"), case_id=None)
        payment_gateway = AsyncMock()
        payment_gateway.authorize.return_value.risk_level = "elevated"
        payment_gateway.authorize.return_value.payment_intent_id = "pi_test_1"
        payment_gateway.cancel.side_effect = RuntimeError("stripe unreachable")
        service = CheckoutService(coordinator, cases_repo, payment_gateway)

        result = await service.checkout(
            account_id="acct_1",
            amount=10.0,
            merchant_id="m1",
            device_context="known_device",
            geo_context="usual_location",
            recent_password_reset=False,
            mfa_completed=True,
            failed_logins_this_session=0,
            test_card="elevated",
        )

        assert result.pipeline_error is not None
        assert "also failed" in result.pipeline_error
        assert "pi_test_1" in result.pipeline_error

    async def test_pipeline_failure_with_a_case_created_leaves_the_authorization_alone(self):
        """Once a case exists (e.g. only the notify() stage failed), it's
        queued/escalated normally and the analyst's approve/deny is the
        correct way to resolve its payment -- cancelling behind its back
        here would corrupt that case's state."""
        service, coordinator, _cases_repo, payment_gateway = make_service()
        case_id = uuid4()
        coordinator.handle_signal.side_effect = CoordinatorError(
            "sig_1", "notify", RuntimeError("missing_scope"), case_id=case_id
        )

        result = await service.checkout(
            account_id="acct_1",
            amount=10.0,
            merchant_id="m1",
            device_context="known_device",
            geo_context="usual_location",
            recent_password_reset=False,
            mfa_completed=True,
            failed_logins_this_session=0,
            test_card="elevated",
        )

        assert result.pipeline_error is not None
        assert payment_gateway.captured == []
        assert payment_gateway.cancelled == []

    async def test_low_route_capture_failure_marks_the_case_error_for_retry(self):
        service, coordinator, cases_repo, payment_gateway = make_service()
        coordinator.handle_signal.return_value.case_id = uuid4()
        coordinator.handle_signal.return_value.status = CaseStatus.CLOSED
        coordinator.handle_signal.return_value.route = Route.LOW
        payment_gateway.capture = AsyncMock(side_effect=RuntimeError("stripe unreachable"))

        result = await service.checkout(
            account_id="acct_1",
            amount=10.0,
            merchant_id="m1",
            device_context="known_device",
            geo_context="usual_location",
            recent_password_reset=False,
            mfa_completed=True,
            failed_logins_this_session=0,
            test_card="elevated",
        )

        assert result.pipeline_error is not None
        cases_repo.update_status.assert_awaited_once_with(
            coordinator.handle_signal.return_value.case_id,
            current_statuses=(CaseStatus.CLOSED,),
            new_status=CaseStatus.ERROR,
            current_resolution=Resolution.NONE,
        )

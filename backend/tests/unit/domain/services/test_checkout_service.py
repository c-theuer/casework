from unittest.mock import AsyncMock

import pytest

from app.domain.entities import CaseStatus, Route
from app.domain.services import AuthorizationDeclinedError, CheckoutService, CoordinatorError
from app.infrastructure.payments.stub_gateway import StubPaymentGateway


def make_service(coordinator=None):
    coordinator = coordinator or AsyncMock()
    # StubPaymentGateway is a real, deterministic collaborator here (not a
    # mock) -- it's exactly as fast/free as mocking Stripe would be, but
    # exercises CheckoutService._authorize()'s actual translation of
    # PaymentDeclinedError -> AuthorizationDeclinedError instead of assuming it.
    payment_gateway = StubPaymentGateway()
    return CheckoutService(coordinator, payment_gateway), coordinator, payment_gateway


@pytest.mark.asyncio
class TestCheckoutService:
    async def test_elevated_card_succeeds_and_creates_a_case(self):
        service, coordinator, payment_gateway = make_service()
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
        service, coordinator, payment_gateway = make_service()
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
        service, coordinator, payment_gateway = make_service()

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
        service, coordinator, payment_gateway = make_service()

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

    async def test_pipeline_failure_after_charge_is_reported_not_raised(self):
        """The auth path is independent of the investigation queue: a
        downstream pipeline failure must not take down the charge result."""
        service, coordinator, payment_gateway = make_service()
        coordinator.handle_signal.side_effect = CoordinatorError("sig_1", "triage", RuntimeError("x"))

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
        assert payment_gateway.captured == []

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import stripe

from app.config import Settings
from app.domain.gateways import PaymentDeclinedError
from app.infrastructure.payments.stripe_gateway import StripePaymentGateway


def make_settings() -> Settings:
    return Settings(stripe_secret_key="sk_test_123", database_url="postgresql://x:x@localhost/x")


def make_gateway_with_mock_client() -> tuple[StripePaymentGateway, MagicMock]:
    with patch("stripe.StripeClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        gateway = StripePaymentGateway(make_settings())
    return gateway, mock_client


@pytest.mark.asyncio
class TestStripePaymentGateway:
    async def test_successful_authorization_returns_real_risk_level_and_payment_intent_id(self):
        gateway, mock_client = make_gateway_with_mock_client()
        mock_client.v1.payment_methods.create_async = AsyncMock(return_value=SimpleNamespace(id="pm_abc123"))
        mock_client.v1.payment_intents.create_async = AsyncMock(
            return_value=SimpleNamespace(
                id="pi_abc123",
                latest_charge=SimpleNamespace(outcome=SimpleNamespace(risk_level="elevated")),
            )
        )

        result = await gateway.authorize(amount=10.5, test_card_token="tok_riskLevelElevated")

        assert result.risk_level == "elevated"
        assert result.payment_intent_id == "pi_abc123"

        _, pm_kwargs = mock_client.v1.payment_methods.create_async.call_args
        assert pm_kwargs["params"]["card"]["token"] == "tok_riskLevelElevated"

        _, pi_kwargs = mock_client.v1.payment_intents.create_async.call_args
        params = pi_kwargs["params"]
        assert params["amount"] == 1050  # dollars -> cents
        assert params["payment_method"] == "pm_abc123"
        assert params["capture_method"] == "manual"
        assert params["confirm"] is True

    async def test_card_error_raises_payment_declined_error(self):
        gateway, mock_client = make_gateway_with_mock_client()
        mock_client.v1.payment_methods.create_async = AsyncMock(return_value=SimpleNamespace(id="pm_abc123"))
        mock_client.v1.payment_intents.create_async = AsyncMock(
            side_effect=stripe.CardError(message="Your card was declined.", param=None, code="card_declined")
        )

        with pytest.raises(PaymentDeclinedError):
            await gateway.authorize(amount=5.0, test_card_token="tok_chargeDeclinedFraudulent")

    async def test_missing_outcome_raises_payment_declined_error(self):
        """Defensive case mypy flagged: stripe-python types latest_charge and
        its outcome as optional even though a non-CardError response always
        has both in practice when latest_charge is expanded."""
        gateway, mock_client = make_gateway_with_mock_client()
        mock_client.v1.payment_methods.create_async = AsyncMock(return_value=SimpleNamespace(id="pm_abc123"))
        mock_client.v1.payment_intents.create_async = AsyncMock(
            return_value=SimpleNamespace(id="pi_abc123", latest_charge=None)
        )

        with pytest.raises(PaymentDeclinedError):
            await gateway.authorize(amount=5.0, test_card_token="tok_riskLevelElevated")

    async def test_capture_calls_the_capture_endpoint(self):
        gateway, mock_client = make_gateway_with_mock_client()
        mock_client.v1.payment_intents.capture_async = AsyncMock(return_value=SimpleNamespace(status="succeeded"))

        await gateway.capture("pi_abc123")

        mock_client.v1.payment_intents.capture_async.assert_awaited_once_with("pi_abc123")

    async def test_cancel_calls_the_cancel_endpoint(self):
        gateway, mock_client = make_gateway_with_mock_client()
        mock_client.v1.payment_intents.cancel_async = AsyncMock(return_value=SimpleNamespace(status="canceled"))

        await gateway.cancel("pi_abc123")

        mock_client.v1.payment_intents.cancel_async.assert_awaited_once_with("pi_abc123")

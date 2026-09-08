import stripe

from app.config import Settings
from app.domain.gateways import AuthorizationResult, PaymentDeclinedError, PaymentGateway


class StripePaymentGateway(PaymentGateway):
    """Real Stripe test-mode authorizations using Radar's documented special
    test tokens (spec §6, docs.stripe.com/radar/testing) -- these simulate a
    specific outcome.risk_level without needing raw card numbers
    server-side.

    Uses PaymentIntents with `capture_method="manual"`, not the legacy
    Charges API: `authorize()` only holds funds (status ends up
    `requires_capture`), it never captures. Money only actually moves later,
    via a deliberate `capture()` call once Casework's own pipeline (and, for
    non-low routes, a human) has decided the transaction should go through;
    `cancel()` releases the hold instead. This means there's never a
    completed charge to refund -- the whole point of holding first.

    The Radar test tokens (`tok_riskLevelElevated` etc.) aren't accepted
    directly as a PaymentIntent's `payment_method` -- they're bridged via a
    PaymentMethod created from the token first (verified empirically against
    a real test-mode account: `payment_methods.create(type="card",
    card={"token": ...})` then `payment_intents.create(payment_method=pm.id,
    confirm=True, capture_method="manual")`). `payment_method_types=["card"]`
    is required too, otherwise Stripe's automatic-payment-methods default
    demands a `return_url` for potential redirect-based methods we never use
    here.

    Note on `tok_riskLevelHighest`: per Stripe's own docs, it "results in a
    charge with a risk level of highest, but could be blocked depending on
    the rules you have in place" -- a fresh Stripe account's default Radar
    ruleset has "Block if risk_level = 'highest'" ON, so this token declines
    at confirmation (a CardError) identically to the always-blocked token
    until that default rule is disabled or adjusted in Dashboard -> Radar ->
    Rules (test mode). Verified this against a real test-mode account.
    """

    def __init__(self, settings: Settings):
        self._client = stripe.StripeClient(settings.stripe_secret_key)

    async def authorize(self, *, amount: float, test_card_token: str) -> AuthorizationResult:
        try:
            payment_method = await self._client.v1.payment_methods.create_async(
                params={"type": "card", "card": {"token": test_card_token}}
            )
            intent = await self._client.v1.payment_intents.create_async(
                params={
                    "amount": round(amount * 100),
                    "currency": "usd",
                    "payment_method": payment_method.id,
                    "payment_method_types": ["card"],
                    "capture_method": "manual",
                    "confirm": True,
                    "description": "Casework demo authorization",
                    "expand": ["latest_charge"],
                }
            )
        except stripe.CardError as exc:
            raise PaymentDeclinedError(str(exc)) from exc

        charge = intent.latest_charge
        if charge is None or isinstance(charge, str) or charge.outcome is None or charge.outcome.risk_level is None:
            # Shouldn't happen for an authorization that didn't raise
            # CardError -- Radar always attaches an outcome to the charge
            # a confirmed PaymentIntent creates -- but stripe-python's own
            # types mark all of these as optional, and `latest_charge` is a
            # bare string unless expanded.
            raise PaymentDeclinedError("Stripe returned no Radar outcome for this authorization")
        return AuthorizationResult(risk_level=charge.outcome.risk_level, payment_intent_id=intent.id)

    async def capture(self, payment_intent_id: str) -> None:
        await self._client.v1.payment_intents.capture_async(payment_intent_id)

    async def cancel(self, payment_intent_id: str) -> None:
        await self._client.v1.payment_intents.cancel_async(payment_intent_id)

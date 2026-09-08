import uuid
from datetime import UTC, datetime
from typing import Literal, TypedDict

from app.domain.entities import Case, CaseSource, Route, Signal
from app.domain.gateways import PaymentDeclinedError, PaymentGateway
from app.domain.services.coordinator_service import CoordinatorError, CoordinatorService

TestCardKey = Literal["elevated", "highest_not_blocked", "highest_blocked"]


class _TestCard(TypedDict):
    number: str
    token: str
    risk_level: str


# The three documented Stripe Radar test-mode cards and their equivalent
# special test tokens (spec §6, docs.stripe.com/radar/testing) -- tokens let
# us simulate a specific outcome.risk_level server-side without needing raw
# card numbers. `risk_level` here is only the *expected* value, used as a
# fallback when a charge is declined and Stripe's error response doesn't
# reliably carry the real one back; a successful charge reports its actual
# outcome.risk_level from Stripe instead.
TEST_CARDS: dict[TestCardKey, _TestCard] = {
    "elevated": {
        "number": "4000000000009235",
        "token": "tok_riskLevelElevated",
        "risk_level": "elevated",
    },
    "highest_not_blocked": {
        "number": "4000000000004954",
        "token": "tok_riskLevelHighest",
        "risk_level": "highest",
    },
    "highest_blocked": {
        "number": "4100000000000019",
        "token": "tok_chargeDeclinedFraudulent",
        "risk_level": "highest",
    },
}


class AuthorizationDeclinedError(Exception):
    """Stripe itself blocked the authorization before our backend ever
    created a Signal -- the architecture boundary the spec's always-blocked
    test card is meant to demonstrate on camera."""

    def __init__(self, risk_level: str):
        super().__init__(f"Authorization declined by Stripe Radar (risk_level={risk_level})")
        self.risk_level = risk_level


_RISK_LEVEL_TO_SCORE = {"elevated": 0.6, "highest": 0.92}


class CheckoutResult:
    def __init__(
        self,
        *,
        risk_level: str,
        payment_intent_id: str,
        case: Case | None = None,
        pipeline_error: str | None = None,
    ):
        self.risk_level = risk_level
        self.payment_intent_id = payment_intent_id
        self.case = case
        self.pipeline_error = pipeline_error


class CheckoutService:
    """Depends on the PaymentGateway port (never the concrete Stripe SDK)
    and the concrete CoordinatorService -- CoordinatorService is a
    domain-to-domain collaborator, not an infrastructure boundary, since it
    itself only ever depends on Protocols."""

    def __init__(
        self,
        coordinator: CoordinatorService,
        payment_gateway: PaymentGateway,
        source: CaseSource = CaseSource.LIVE_STRIPE,
    ):
        self._coordinator = coordinator
        self._payment_gateway = payment_gateway
        self._source = source

    async def _authorize(self, test_card: TestCardKey, amount: float) -> tuple[str, str]:
        """Returns (risk_level, payment_intent_id) or raises
        AuthorizationDeclinedError. The returned PaymentIntent is only
        authorized (held), never captured -- see checkout() for what
        happens to that hold next."""
        card = TEST_CARDS[test_card]
        try:
            result = await self._payment_gateway.authorize(amount=amount, test_card_token=card["token"])
        except PaymentDeclinedError as exc:
            raise AuthorizationDeclinedError(card["risk_level"]) from exc
        return result.risk_level, result.payment_intent_id

    async def checkout(
        self,
        *,
        account_id: str,
        amount: float,
        merchant_id: str,
        device_context: str,
        geo_context: str,
        recent_password_reset: bool,
        mfa_completed: bool,
        failed_logins_this_session: int,
        test_card: TestCardKey,
    ) -> CheckoutResult:
        risk_level, payment_intent_id = await self._authorize(test_card, amount)

        upstream_score = _RISK_LEVEL_TO_SCORE[risk_level]
        flag_reason = f"stripe_radar_{risk_level}"

        signal = Signal(
            signal_id=f"sig_{uuid.uuid4().hex}",
            signal_type="transaction",
            occurred_at=datetime.now(UTC),
            account_id=account_id,
            upstream_score=upstream_score,
            flag_reason=flag_reason,
            payload={
                "amount": amount,
                "merchant_id": merchant_id,
                "device_context": device_context,
                "geo_context": geo_context,
                "session_flags": {
                    "recent_password_reset": recent_password_reset,
                    "mfa_completed": mfa_completed,
                    "failed_logins_this_session": failed_logins_this_session,
                },
                "stripe_payment_intent_id": payment_intent_id,
            },
        )

        try:
            case = await self._coordinator.handle_signal(signal, source=self._source)
        except CoordinatorError as exc:
            # The auth path is independent of the investigation queue: the
            # authorization already succeeded, so we still report that
            # success even if triage/research/synthesis blew up downstream.
            # The PaymentIntent is left held (requires_capture) rather than
            # captured or cancelled here -- with no persisted case, there's
            # nothing for a human to approve/deny to resolve it, a gap
            # worth a real retry/reconciliation queue in production rather
            # than guessing at a resolution from here.
            return CheckoutResult(
                risk_level=risk_level,
                payment_intent_id=payment_intent_id,
                pipeline_error=str(exc),
            )

        if case.route == Route.LOW:
            # Nothing ever reviews a low-risk case -- the pipeline itself
            # is the approval, so capture immediately rather than leave the
            # hold dangling until Stripe's own 7-day auto-cancellation.
            try:
                await self._payment_gateway.capture(payment_intent_id)
            except Exception as exc:  # noqa: BLE001 -- PaymentGateway is a Protocol; report whatever it raises
                return CheckoutResult(
                    risk_level=risk_level,
                    payment_intent_id=payment_intent_id,
                    case=case,
                    pipeline_error=f"Case auto-cleared but capturing the authorization failed: {exc}",
                )

        return CheckoutResult(risk_level=risk_level, payment_intent_id=payment_intent_id, case=case)

import uuid
from datetime import UTC, datetime
from typing import Literal, TypedDict

from app.domain.entities import Case, CaseSource, Signal
from app.domain.services.coordinator_service import CoordinatorError, CoordinatorService

TestCardKey = Literal["elevated", "highest_not_blocked", "highest_blocked"]


class _TestCard(TypedDict):
    number: str
    risk_level: str
    blocked_by_stripe: bool


# The three documented Stripe Radar test-mode cards (spec §6). Phase 1 stubs
# the actual Stripe API call; Phase 2 replaces `_charge()` with a real
# stripe.PaymentIntent.create(...) call and reads outcome.risk_level back for
# real instead of looking it up here.
TEST_CARDS: dict[TestCardKey, _TestCard] = {
    "elevated": {"number": "4000000000009235", "risk_level": "elevated", "blocked_by_stripe": False},
    "highest_not_blocked": {
        "number": "4000000000004954",
        "risk_level": "highest",
        "blocked_by_stripe": False,
    },
    "highest_blocked": {
        "number": "4100000000000019",
        "risk_level": "highest",
        "blocked_by_stripe": True,
    },
}


class ChargeDeclinedError(Exception):
    """Stripe itself blocked the charge before our backend ever created a
    Signal -- the architecture boundary the spec's always-blocked test card
    is meant to demonstrate on camera."""

    def __init__(self, risk_level: str):
        super().__init__(f"Charge declined by Stripe Radar (risk_level={risk_level})")
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
    """Depends on the concrete CoordinatorService (a domain-to-domain
    collaborator, not an infrastructure boundary -- CoordinatorService
    itself only ever depends on Protocols, so there's no concrete
    persistence/API class to invert here)."""

    def __init__(self, coordinator: CoordinatorService, source: CaseSource = CaseSource.LIVE_STRIPE):
        self._coordinator = coordinator
        self._source = source

    def _charge(self, test_card: TestCardKey) -> tuple[str, str]:
        """Stub Stripe charge. Returns (risk_level, payment_intent_id) or
        raises ChargeDeclinedError. Phase 2 replaces this body only."""
        card = TEST_CARDS[test_card]
        if card["blocked_by_stripe"]:
            raise ChargeDeclinedError(card["risk_level"])
        return card["risk_level"], f"pi_stub_{uuid.uuid4().hex[:16]}"

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
        risk_level, payment_intent_id = self._charge(test_card)

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
            return CheckoutResult(risk_level=risk_level, payment_intent_id=payment_intent_id, case=case)
        except CoordinatorError as exc:
            # The auth path is independent of the investigation queue: the
            # charge already succeeded, so we still report that success even
            # if triage/research/synthesis blew up downstream.
            return CheckoutResult(
                risk_level=risk_level,
                payment_intent_id=payment_intent_id,
                pipeline_error=str(exc),
            )

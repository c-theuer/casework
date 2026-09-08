import uuid

from app.domain.gateways import AuthorizationResult, PaymentDeclinedError, PaymentGateway
from app.domain.services.checkout_service import TEST_CARDS

_RISK_LEVEL_BY_TOKEN = {card["token"]: card["risk_level"] for card in TEST_CARDS.values()}
_BLOCKED_TOKEN = TEST_CARDS["highest_blocked"]["token"]


class StubPaymentGateway(PaymentGateway):
    """Phase 1 adapter: static stand-in for StripePaymentGateway, keyed off
    the same TEST_CARDS risk levels without ever calling Stripe. Kept
    around as a fast, free, fully-deterministic option for tests -- the
    always-blocked token is the only one that raises.

    `captured`/`cancelled` record every payment_intent_id passed to
    capture()/cancel() in call order, so a test can assert on which
    resolution actually happened (e.g. CasesService.approve() on a "block"
    recommendation should cancel, never capture) without needing a mock.
    """

    def __init__(self) -> None:
        self.captured: list[str] = []
        self.cancelled: list[str] = []

    async def authorize(self, *, amount: float, test_card_token: str) -> AuthorizationResult:
        if test_card_token not in _RISK_LEVEL_BY_TOKEN:
            raise ValueError(f"Unknown test card token: {test_card_token}")
        risk_level = _RISK_LEVEL_BY_TOKEN[test_card_token]
        if test_card_token == _BLOCKED_TOKEN:
            raise PaymentDeclinedError(risk_level)
        return AuthorizationResult(
            risk_level=risk_level, payment_intent_id=f"pi_stub_{uuid.uuid4().hex[:16]}"
        )

    async def capture(self, payment_intent_id: str) -> None:
        self.captured.append(payment_intent_id)

    async def cancel(self, payment_intent_id: str) -> None:
        self.cancelled.append(payment_intent_id)

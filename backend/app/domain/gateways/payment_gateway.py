from dataclasses import dataclass
from typing import Protocol


@dataclass
class AuthorizationResult:
    risk_level: str
    payment_intent_id: str


class PaymentDeclinedError(Exception):
    """Raised when the payment gateway itself declines/blocks an
    authorization -- the architecture boundary the spec's always-blocked
    test card is meant to demonstrate: Casework never creates a Signal for
    an authorization that never succeeded."""


class PaymentGateway(Protocol):
    """Port for authorizing a test-mode PaymentIntent (holding funds without
    capturing them) and reading its real Radar risk_level back, then later
    resolving that hold one way or the other.

    Casework never captures a charge before its own triage pipeline has run:
    every PaymentIntent is authorized with manual capture, held in
    `requires_capture`, and only actually captured (money moves) or
    cancelled (hold released, nothing moves) once a route/human decision is
    final. This means there's never a captured-then-reversed charge to
    refund -- see app.domain.services.cases_service.CasesService, which
    makes that capture-vs-cancel call deterministically, and
    app.infrastructure.payments.stripe_gateway.StripePaymentGateway for the
    concrete Stripe implementation."""

    async def authorize(self, *, amount: float, test_card_token: str) -> AuthorizationResult: ...

    async def capture(self, payment_intent_id: str) -> None: ...

    async def cancel(self, payment_intent_id: str) -> None: ...

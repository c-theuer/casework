from fastapi import APIRouter, Depends

from app.api.dependencies import get_checkout_service
from app.api.schemas import CheckoutRequest, CheckoutResponse
from app.domain.services import ChargeDeclinedError, CheckoutService

router = APIRouter(tags=["checkout"])


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(
    request: CheckoutRequest,
    checkout_service: CheckoutService = Depends(get_checkout_service),
) -> CheckoutResponse:
    try:
        result = await checkout_service.checkout(
            account_id=request.account_id,
            amount=request.amount,
            merchant_id=request.merchant_id,
            device_context=request.device_context,
            geo_context=request.geo_context,
            recent_password_reset=request.recent_password_reset,
            mfa_completed=request.mfa_completed,
            failed_logins_this_session=request.failed_logins_this_session,
            test_card=request.test_card,
        )
    except ChargeDeclinedError as exc:
        # Stripe blocked it before we ever created a Signal -- the
        # architecture boundary the always-blocked test card demonstrates.
        return CheckoutResponse(
            charge_succeeded=False,
            risk_level=exc.risk_level,
            signal_created=False,
            message="Charge declined by Stripe Radar. Casework never saw this transaction.",
        )

    if result.pipeline_error:
        return CheckoutResponse(
            charge_succeeded=True,
            risk_level=result.risk_level,
            payment_intent_id=result.payment_intent_id,
            signal_created=True,
            message=f"Charge succeeded, but the triage pipeline failed: {result.pipeline_error}",
        )

    return CheckoutResponse(
        charge_succeeded=True,
        risk_level=result.risk_level,
        payment_intent_id=result.payment_intent_id,
        signal_created=True,
        case_id=result.case.case_id,
        case_status=result.case.status.value,
        message="Charge succeeded and a case was created.",
    )

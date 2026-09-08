from fastapi import APIRouter, Depends

from app.api.dependencies import get_checkout_service
from app.api.schemas import CheckoutRequest, CheckoutResponse
from app.domain.services import AuthorizationDeclinedError, CheckoutService

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
    except AuthorizationDeclinedError as exc:
        # Stripe blocked it before we ever created a Signal -- the
        # architecture boundary the always-blocked test card demonstrates.
        return CheckoutResponse(
            authorized=False,
            risk_level=exc.risk_level,
            signal_created=False,
            message="Authorization declined by Stripe Radar. Casework never saw this transaction.",
        )

    if result.pipeline_error:
        return CheckoutResponse(
            authorized=True,
            risk_level=result.risk_level,
            payment_intent_id=result.payment_intent_id,
            signal_created=True,
            message=f"Authorization succeeded, but the triage pipeline failed: {result.pipeline_error}",
        )

    # CheckoutService guarantees exactly one of `case`/`pipeline_error` is
    # set; `pipeline_error` was already ruled out above.
    assert result.case is not None
    return CheckoutResponse(
        authorized=True,
        risk_level=result.risk_level,
        payment_intent_id=result.payment_intent_id,
        signal_created=True,
        case_id=result.case.case_id,
        case_status=result.case.status.value,
        message="Authorization succeeded and a case was created.",
    )

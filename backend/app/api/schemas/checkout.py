from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CheckoutRequest(BaseModel):
    account_id: str
    amount: float = Field(gt=0)
    merchant_id: str
    device_context: Literal["known_device", "new_device"]
    geo_context: Literal["usual_location", "new_or_foreign_location"]
    recent_password_reset: bool = False
    mfa_completed: bool = False
    failed_logins_this_session: int = 0
    test_card: Literal["elevated", "highest_not_blocked", "highest_blocked"]


class CheckoutResponse(BaseModel):
    authorized: bool
    risk_level: str | None = None
    payment_intent_id: str | None = None
    signal_created: bool
    case_id: UUID | None = None
    case_status: str | None = None
    message: str

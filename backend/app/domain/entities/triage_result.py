from typing import Literal

from pydantic import BaseModel


class TriageResult(BaseModel):
    signal_id: str
    pattern: Literal[
        "card_testing",
        "account_takeover",
        "merchant_fraud",
        "mule_activity",
        "friendly_fraud",
        "benign",
    ]
    tier: Literal["low", "elevated", "critical"]
    confidence: float
    entities: dict

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Signal(BaseModel):
    signal_id: str
    signal_type: Literal["transaction", "login", "chargeback"]
    occurred_at: datetime
    account_id: str
    upstream_score: float
    flag_reason: str
    payload: dict

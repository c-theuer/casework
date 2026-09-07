from typing import Literal

from pydantic import BaseModel


class CaseRecommendation(BaseModel):
    signal_id: str
    risk_score: float
    recommended_action: Literal["block", "flag_for_review", "monitor", "clear"]
    draft_note: str
    requires_human_approval: bool

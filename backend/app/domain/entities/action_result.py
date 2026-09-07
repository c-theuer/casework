from datetime import datetime

from pydantic import BaseModel


class ActionResult(BaseModel):
    signal_id: str
    action_taken: str
    executed_by: str
    approved_by: str
    timestamp: datetime

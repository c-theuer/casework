from pydantic import BaseModel


class ApproveRequest(BaseModel):
    approved_by: str


class DenyRequest(BaseModel):
    denied_by: str

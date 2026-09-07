from pydantic import BaseModel, ConfigDict


class Rule(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    pattern: str | None
    title: str
    description: str
    active: bool

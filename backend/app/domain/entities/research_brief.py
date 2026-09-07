from pydantic import BaseModel


class ResearchBrief(BaseModel):
    signal_id: str
    matched_rules: list[str]
    similar_cases: list[str]
    evidence: list[str]

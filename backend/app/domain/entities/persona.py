from typing import Literal

from pydantic import BaseModel, ConfigDict


class Persona(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    display_name: str
    tenure_days: int
    lifetime_volume_cents: int
    prior_case_count: int
    default_device_context: Literal["known_device", "new_device"]
    default_geo_context: Literal["usual_location", "new_or_foreign_location"]

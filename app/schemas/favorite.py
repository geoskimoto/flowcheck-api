from datetime import datetime
from pydantic import BaseModel


class FavoriteRequest(BaseModel):
    station_number: str


class FavoriteResponse(BaseModel):
    station_number: str
    added_at: datetime

    model_config = {"from_attributes": True}

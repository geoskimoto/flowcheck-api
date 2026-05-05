from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class AlertSubscriptionRequest(BaseModel):
    station_number: str


class AlertSubscriptionResponse(BaseModel):
    station_number: str
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertEventResponse(BaseModel):
    station_number: str
    percentile_rank: float
    triggered_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DeviceRegisterRequest(BaseModel):
    fcm_token: str
    platform: str  # "ios" | "android"

    def model_post_init(self, __context):
        if self.platform not in ("ios", "android"):
            raise ValueError("platform must be 'ios' or 'android'")

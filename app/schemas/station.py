from typing import Optional
from pydantic import BaseModel


class StationSummary(BaseModel):
    station_number: str
    name: str
    latitude: float
    longitude: float
    state: str
    is_active: bool
    current_discharge_cfs: Optional[float] = None
    percentile_rank: Optional[float] = None
    condition_band: Optional[str] = None
    condition_label: str = "Unknown"
    has_forecast: bool = False
    last_observation_date: Optional[str] = None  # ISO date

    model_config = {"from_attributes": True}


class StationDetail(StationSummary):
    huc_code: Optional[str] = None
    basin: Optional[str] = None
    years_of_record: Optional[int] = None
    record_start_date: Optional[str] = None

from pydantic import BaseModel


class ForecastPoint(BaseModel):
    date: str   # ISO 8601 timestamp
    value: float  # discharge in CFS


class ForecastResponse(BaseModel):
    station_number: str  # USGS station number
    nwrfc_code: str      # NWRFC/NWS code the forecast is keyed by
    source: str          # e.g. "NOAA_RFC"
    run_date: str        # ISO 8601 timestamp of the forecast run
    points: list[ForecastPoint]

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.forecast import ForecastResponse
from app.schemas.station import StationSummary, StationDetail
from app.services.forecast_service import get_forecast_service
from app.services.streamflow_service import get_streamflow_service
from app.services.water_year_service import (
    WaterYearDataUnavailable,
    get_current_water_year_series,
    get_water_year_stats,
)

router = APIRouter(prefix="/stations", tags=["stations"])


@router.get("/", response_model=list[StationSummary])
def list_stations(state: Optional[str] = None):
    svc = get_streamflow_service()
    return svc.list_stations(state=state)


@router.get("/{station_number}/water-year-stats")
def water_year_stats(station_number: str, db: Session = Depends(get_db)):
    try:
        stats = get_water_year_stats(station_number, db)
    except WaterYearDataUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Water year statistics temporarily unavailable — please retry",
        )
    if not stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No sufficient historical data for this station",
        )
    return stats


@router.get("/{station_number}/current-water-year")
def current_water_year(station_number: str):
    try:
        return get_current_water_year_series(station_number)
    except WaterYearDataUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Current water year data temporarily unavailable — please retry",
        )


@router.get("/{station_number}/forecast", response_model=ForecastResponse)
def station_forecast(station_number: str):
    fc = get_forecast_service().get_forecast(station_number)
    if fc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No NWRFC forecast available for this station",
        )
    return fc


@router.get("/{station_number}", response_model=StationDetail)
def get_station(station_number: str):
    svc = get_streamflow_service()
    station = svc.get_station(station_number)
    if station is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Station not found")
    return station

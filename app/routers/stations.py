from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.station import StationSummary, StationDetail
from app.services.streamflow_service import get_streamflow_service
from app.services.water_year_service import get_water_year_stats

router = APIRouter(prefix="/stations", tags=["stations"])


@router.get("/", response_model=list[StationSummary])
def list_stations(state: Optional[str] = None):
    svc = get_streamflow_service()
    return svc.list_stations(state=state)


@router.get("/{station_number}/water-year-stats")
def water_year_stats(station_number: str, db: Session = Depends(get_db)):
    stats = get_water_year_stats(station_number, db)
    if stats is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Water year statistics unavailable — insufficient historical data or upstream API error",
        )
    return stats


@router.get("/{station_number}", response_model=StationDetail)
def get_station(station_number: str):
    svc = get_streamflow_service()
    station = svc.get_station(station_number)
    if station is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Station not found")
    return station

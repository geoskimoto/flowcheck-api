from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StationCache(Base):
    """Persistent mirror of the in-memory station catalog.

    Loaded on service init so an API restart doesn't need a successful
    upstream call to serve the map. Refreshed by streamflow_service when
    upstream succeeds. last_observation_date is updated by the separate
    last-observation refresh, so the two upserts never clobber each other.
    """
    __tablename__ = "stations_cache"

    station_number: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    state: Mapped[str] = mapped_column(String, nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Optional detail-ish fields surfaced on /stations/{id}
    huc_code: Mapped[str] = mapped_column(String, nullable=True)
    basin: Mapped[str] = mapped_column(String, nullable=True)
    years_of_record: Mapped[int] = mapped_column(Integer, nullable=True)
    record_start_date: Mapped[str] = mapped_column(String, nullable=True)

    # Updated by the last-observation refresh (separate from station refresh)
    last_observation_date: Mapped[str] = mapped_column(String, nullable=True)

    # Bookkeeping
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

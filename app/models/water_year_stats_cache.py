from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WaterYearStatsCache(Base):
    __tablename__ = "water_year_stats_cache"

    station_number: Mapped[str] = mapped_column(String, primary_key=True)
    water_year: Mapped[int] = mapped_column(Integer, nullable=False)
    # List of {day_of_wy, q10, q25, q50, q75, q90, mean} dicts
    stats_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    station_number: Mapped[str] = mapped_column(String, nullable=False, index=True)
    percentile_rank: Mapped[float] = mapped_column(Float, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

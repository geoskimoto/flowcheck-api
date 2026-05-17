import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.water_year_stats_cache import WaterYearStatsCache

logger = logging.getLogger(__name__)

WY_START_MONTH = 10


def _current_water_year() -> int:
    now = datetime.now()
    return now.year + 1 if now.month >= WY_START_MONTH else now.year


def _get_water_year(date: pd.Timestamp) -> int:
    return date.year + 1 if date.month >= WY_START_MONTH else date.year


def _get_day_of_water_year(date: pd.Timestamp) -> int:
    wy_start_year = date.year if date.month >= WY_START_MONTH else date.year - 1
    wy_start = pd.Timestamp(wy_start_year, WY_START_MONTH, 1)
    return (date - wy_start).days + 1


def compute_water_year_stats(
    station_number: str,
    discharge_df: pd.DataFrame,
    current_water_year: Optional[int] = None,
) -> list[dict]:
    """
    Compute per-day-of-water-year percentile statistics from historical discharge data.
    Excludes the current (in-progress) water year.
    Returns a list of dicts with keys: day_of_wy, q10, q25, q50, q75, q90, mean.
    Returns [] if insufficient data (< 365 historical rows).
    """
    if current_water_year is None:
        current_water_year = _current_water_year()

    if discharge_df.empty:
        return []

    df = discharge_df.copy()

    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("datetime", "date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
                df = df.set_index(col)
                break

    if not isinstance(df.index, pd.DatetimeIndex):
        logger.warning(f"{station_number}: cannot compute stats — no DatetimeIndex")
        return []

    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    df = df.dropna()

    value_col = next(
        (c for c in df.columns if any(t in c.lower() for t in ("discharge", "flow", "00060"))),
        None,
    )
    if value_col is None:
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) == 0:
            logger.warning(f"{station_number}: no numeric discharge column found")
            return []
        value_col = numeric_cols[0]

    df["water_year"] = df.index.map(_get_water_year)
    df["day_of_wy"] = df.index.map(_get_day_of_water_year)

    historical = df[df["water_year"] < current_water_year].copy()

    if len(historical) < 365:
        logger.warning(f"{station_number}: insufficient historical data ({len(historical)} rows)")
        return []

    stats = (
        historical.groupby("day_of_wy")[value_col]
        .agg(
            q10=lambda x: x.quantile(0.10),
            q25=lambda x: x.quantile(0.25),
            q50=lambda x: x.quantile(0.50),
            q75=lambda x: x.quantile(0.75),
            q90=lambda x: x.quantile(0.90),
            mean="mean",
        )
        .reset_index()
        .rename(columns={"day_of_wy": "day_of_wy"})
    )

    return stats.to_dict(orient="records")


def get_water_year_stats(station_number: str, db: Session) -> Optional[list[dict]]:
    """
    Return cached water year stats for a station, computing if cache is stale or missing.
    Cache is valid for the entire current water year (invalidates Oct 1).
    Returns None if computation fails (insufficient data or API error).
    """
    current_wy = _current_water_year()

    cached = db.query(WaterYearStatsCache).filter(
        WaterYearStatsCache.station_number == station_number,
        WaterYearStatsCache.water_year == current_wy,
    ).first()

    if cached:
        logger.debug(f"Water year stats cache HIT: {station_number} WY{current_wy}")
        return cached.stats_json

    logger.info(f"Water year stats cache MISS: computing {station_number} WY{current_wy}")
    stats = _fetch_and_compute(station_number, current_wy)
    if not stats:
        return None

    _upsert_cache(db, station_number, current_wy, stats)
    return stats


def _fetch_and_compute(station_number: str, current_wy: int) -> list[dict]:
    settings = get_settings()
    try:
        from dataops_client.client import DataOpsClient
        client = DataOpsClient(
            base_url=settings.dataops_api_url,
            api_token=settings.dataops_api_token,
            timeout=settings.dataops_timeout,
        )
        # get_station_data requires an explicit date range. Water-year percentiles
        # need the full historical record, so request a wide window.
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * 40)
        observations = client.get_station_data(
            station_number,
            start_date=start_date,
            end_date=end_date,
            data_type="daily_mean",
        )
        if not observations:
            return []

        rows = []
        for obs in observations:
            # DischargeObservation exposes observed_at (tz-aware) + discharge_value.
            observed_at = obs.observed_at
            if observed_at is not None and observed_at.tzinfo is not None:
                observed_at = observed_at.replace(tzinfo=None)
            rows.append({"date": observed_at, "discharge": obs.discharge_value})

        df = pd.DataFrame(rows)
        if df.empty:
            return []
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.set_index("date").rename(columns={"discharge": "discharge_cfs"})

        return compute_water_year_stats(station_number, df, current_water_year=current_wy)
    except Exception as e:
        logger.error(f"Failed to fetch/compute water year stats for {station_number}: {e}")
        return []


def _upsert_cache(db: Session, station_number: str, water_year: int, stats: list[dict]):
    try:
        existing = db.query(WaterYearStatsCache).filter(
            WaterYearStatsCache.station_number == station_number
        ).first()
        if existing:
            existing.water_year = water_year
            existing.stats_json = stats
            existing.computed_at = datetime.now(timezone.utc)
        else:
            db.add(WaterYearStatsCache(
                station_number=station_number,
                water_year=water_year,
                stats_json=stats,
            ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to cache water year stats for {station_number}: {e}")

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


class WaterYearDataUnavailable(Exception):
    """Transient upstream failure — caller should retry, must NOT be cached."""


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


def get_water_year_stats(station_number: str, db: Session) -> list[dict]:
    """
    Return cached water year stats, computing on cache miss.

    Returns a list of per-day-of-WY stat dicts, or [] when the station has
    no/insufficient historical daily record (a definitive, cacheable fact
    for this water year). Raises WaterYearDataUnavailable on a transient
    upstream failure (not cached — safe to retry).
    """
    current_wy = _current_water_year()

    cached = db.query(WaterYearStatsCache).filter(
        WaterYearStatsCache.station_number == station_number,
        WaterYearStatsCache.water_year == current_wy,
    ).first()

    if cached is not None:
        # stats_json may legitimately be [] (cached "insufficient history").
        logger.debug(f"Water year stats cache HIT: {station_number} WY{current_wy}")
        return cached.stats_json or []

    logger.info(f"Water year stats cache MISS: computing {station_number} WY{current_wy}")
    # _fetch_and_compute raises WaterYearDataUnavailable on transient failure;
    # that propagates (uncached). A definitive [] IS cached so a no-data
    # station isn't re-fetched (30yr) on every view.
    stats = _fetch_and_compute(station_number, current_wy)
    _upsert_cache(db, station_number, current_wy, stats)
    return stats


def get_current_water_year_series(station_number: str) -> list[dict]:
    """
    Current (in-progress) water year's observed daily discharge as
    [{day_of_wy, discharge}], sorted by day_of_wy. Small Oct1->today fetch.
    Raises WaterYearDataUnavailable on transient upstream failure.
    """
    current_wy = _current_water_year()
    wy_start = datetime(current_wy - 1, WY_START_MONTH, 1)
    end_date = datetime.now()

    observations = _get_station_data_with_retry(station_number, wy_start, end_date)
    out: list[dict] = []
    for obs in observations or []:
        observed_at = obs.observed_at
        if observed_at is None or obs.discharge_value is None:
            continue
        if observed_at.tzinfo is not None:
            observed_at = observed_at.replace(tzinfo=None)
        out.append({
            "day_of_wy": _get_day_of_water_year(pd.Timestamp(observed_at)),
            "discharge": obs.discharge_value,
        })
    out.sort(key=lambda r: r["day_of_wy"])
    return out


def _get_station_data_with_retry(station_number, start_date, end_date):
    """
    Fetch daily-mean observations, retrying through StreamflowOps' frequent
    connection resets. Raises WaterYearDataUnavailable if all attempts fail.
    """
    settings = get_settings()
    from dataops_client.client import DataOpsClient
    client = DataOpsClient(
        base_url=settings.dataops_api_url,
        api_token=settings.dataops_api_token,
        timeout=settings.dataops_timeout,
    )
    last_err = None
    for _ in range(3):
        try:
            return client.get_station_data(
                station_number,
                start_date=start_date,
                end_date=end_date,
                data_type="daily_mean",
            )
        except Exception as e:  # noqa: BLE001 — retry any transient
            last_err = e
    logger.warning(f"Station data fetch failed for {station_number}: {last_err}")
    raise WaterYearDataUnavailable(str(last_err))


def _fetch_and_compute(station_number: str, current_wy: int) -> list[dict]:
    # 30yr window (was 40): the larger the window the longer/more reset-prone
    # the cold fetch; 30yr is ample for stable per-day-of-WY percentiles.
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365 * 30)

    # Raises WaterYearDataUnavailable on transient failure (propagates,
    # uncached). A successful-but-empty response is a definitive "no data".
    observations = _get_station_data_with_retry(station_number, start_date, end_date)
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

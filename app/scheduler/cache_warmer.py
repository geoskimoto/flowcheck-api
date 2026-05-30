"""Nightly background warm of water_year_stats_cache.

Each nightly pass attempts uncached stations within a time budget. Cache
hits skip fast (idempotent), transient failures are retried on a later
pass. Over many nights, the cache fills out — directly powering the
hybrid percentile path in streamflow_service (Option B1) so the map's
self-computed colours grow with cache coverage.
"""
import logging
import time
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def warm_water_year_cache(
    state: Optional[str] = None,
    limit: Optional[int] = None,
    max_seconds: Optional[int] = None,
    prefer_recent_days: int = 14,
) -> dict:
    """Iterate stations and populate water_year_stats_cache.

    - prefer_recent_days: stations whose last_observation_date is within
      this window are processed FIRST so the budget targets gauges users
      actually see (matches the app's hide-inactive default).
    - max_seconds: stop iteration once elapsed exceeds this. The next
      nightly run resumes work because already-cached stations skip fast.
    """
    # Local imports keep module-import cheap when the scheduler boots.
    from app.database import SessionLocal
    from app.services.streamflow_service import get_streamflow_service
    from app.services.water_year_service import (
        WaterYearDataUnavailable,
        get_water_year_stats,
    )

    svc = get_streamflow_service()
    stations = svc.list_stations(state=state)

    if prefer_recent_days and prefer_recent_days > 0:
        cutoff = date.today() - timedelta(days=prefer_recent_days)

        def is_recent(s: dict) -> bool:
            lo = s.get("last_observation_date")
            if not lo:
                return False
            try:
                return date.fromisoformat(lo) >= cutoff
            except ValueError:
                return False

        recent = [s["station_number"] for s in stations if is_recent(s)]
        other = [s["station_number"] for s in stations if not is_recent(s)]
        nums = recent + other
    else:
        nums = [s["station_number"] for s in stations]

    if limit:
        nums = nums[:limit]

    started = time.time()
    total = len(nums)
    attempted = ok = empty = transient = 0
    stopped_for_budget = False
    db = SessionLocal()
    try:
        for sn in nums:
            if max_seconds and (time.time() - started) > max_seconds:
                stopped_for_budget = True
                break
            attempted += 1
            try:
                stats = get_water_year_stats(sn, db)
                if stats:
                    ok += 1
                else:
                    empty += 1
            except WaterYearDataUnavailable:
                transient += 1
            except Exception as e:  # noqa: BLE001
                transient += 1
                logger.warning(f"{sn}: {e}")
    finally:
        db.close()

    return {
        "total": total,
        "attempted": attempted,
        "ok": ok,
        "empty": empty,
        "transient": transient,
        "elapsed_s": round(time.time() - started, 1),
        "stopped_for_budget": stopped_for_budget,
    }


def run_cache_warm(max_seconds: int = 45 * 60) -> None:
    """Scheduler entrypoint — wraps warm_water_year_cache with logging."""
    logger.info(f"Starting nightly water-year cache warm (budget {max_seconds}s)")
    result = warm_water_year_cache(max_seconds=max_seconds)
    logger.info(f"Nightly warm done: {result}")

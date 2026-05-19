import json
import logging
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# NWRFC publishes ~daily; cache for 3h. Stale entries are still served as a
# last-good fallback when the (intermittently unstable) upstream errors.
_FORECAST_TTL = 3 * 3600

# USGS station number -> NWRFC/NWS code. The StreamflowOps forecast endpoint
# is keyed by NWRFC code and StreamflowOps exposes no USGS<->NWRFC crosswalk,
# so this mapping is bundled (sourced from the dashboard's resid-cast config).
_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "usgs_nwrfc_map.json"


@lru_cache
def _usgs_nwrfc_map() -> dict[str, str]:
    try:
        with open(_MAP_PATH) as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to load USGS->NWRFC map: {e}")
        return {}


def station_has_forecast(station_number: str) -> bool:
    """True if the station is in the bundled USGS->NWRFC map."""
    return station_number in _usgs_nwrfc_map()


class ForecastService:
    def __init__(self):
        settings = get_settings()
        from dataops_client.client import DataOpsClient
        self._client = DataOpsClient(
            base_url=settings.dataops_api_url,
            api_token=settings.dataops_api_token,
            timeout=settings.dataops_timeout,
        )
        # station_number -> (fetched_at, payload)
        self._cache: dict[str, tuple[float, dict]] = {}

    def get_forecast(self, station_number: str) -> Optional[dict]:
        """
        Return the latest NWRFC forecast run for a USGS station, or None if
        the station has no NWRFC mapping / no forecast.

        Results are cached for _FORECAST_TTL. StreamflowOps' forecast
        endpoint is intermittently slow/resetting, so on a fresh upstream
        failure a previously cached (even stale) payload is served rather
        than failing the request.
        """
        nwrfc = _usgs_nwrfc_map().get(station_number)
        if not nwrfc:
            return None

        cached = self._cache.get(station_number)
        if cached and (time.time() - cached[0]) < _FORECAST_TTL:
            return cached[1]

        try:
            runs = self._client.get_forecast_by_station(nwrfc, num_days=1)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Forecast fetch failed for {station_number}/{nwrfc}: {e}")
            return cached[1] if cached else None
        if not runs:
            return cached[1] if cached else None

        run = runs[0]  # newest-first
        points = [
            {"date": p["date"], "value": p["value"]}
            for p in (run.get("data") or [])
            if p.get("date") is not None and p.get("value") is not None
        ]
        if not points:
            return cached[1] if cached else None

        payload = {
            "station_number": station_number,
            "nwrfc_code": nwrfc,
            "source": run.get("source", "NOAA_RFC"),
            "run_date": str(run.get("run_date", "")),
            "points": points,
        }
        self._cache[station_number] = (time.time(), payload)
        return payload


_service_instance: Optional[ForecastService] = None


def get_forecast_service() -> ForecastService:
    global _service_instance
    if _service_instance is None:
        _service_instance = ForecastService()
    return _service_instance

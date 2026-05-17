import time
import logging
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

BAND_LABELS = {
    "p0_4": "Very Low",
    "p5_10": "Low",
    "p11_25": "Below Normal",
    "p26_50": "Normal",
    "p51_75": "Above Normal",
    # StreamflowOps splits the high end finer than the original p76_100 bucket.
    "p76_100": "High",
    "p76_85": "High",
    "p86_90": "High",
    "p91_95": "Very High",
    "p96_98": "Very High",
    "p99_100": "Extremely High",
}

PNW_STATES = ["WA", "OR", "ID"]


def band_to_label(band: str) -> str:
    return BAND_LABELS.get(band, "Unknown")


class StreamflowService:
    def __init__(self):
        settings = get_settings()
        from dataops_client.client import DataOpsClient
        self._client = DataOpsClient(
            base_url=settings.dataops_api_url,
            api_token=settings.dataops_api_token,
            timeout=settings.dataops_timeout,
        )
        self._station_cache: list = []
        self._station_cache_time: float = 0.0
        self._percentile_cache: dict = {}
        self._percentile_cache_time: float = 0.0

    def _stations_stale(self) -> bool:
        settings = get_settings()
        return (time.time() - self._station_cache_time) > settings.station_cache_ttl

    def _percentiles_stale(self) -> bool:
        return (time.time() - self._percentile_cache_time) > 1800  # 30 min

    def _fetch_percentiles(self) -> dict:
        if not self._percentiles_stale():
            return self._percentile_cache
        try:
            resp = self._client._request("GET", "/api/v1/observations/discharge/percentile-bands/", params={"days_back": 2})
            self._percentile_cache = {
                r["station_number"]: {
                    "band": r.get("band", ""),
                    "percentile_rank": r.get("percentile_rank", 0.0),
                    "current_discharge": r.get("discharge", 0.0),
                }
                for r in resp.get("results", [])
            }
            self._percentile_cache_time = time.time()
        except Exception as e:
            logger.warning(f"Percentile fetch failed: {e}")
        return self._percentile_cache

    def list_stations(self, state: Optional[str] = None) -> list[dict]:
        if self._stations_stale():
            self._refresh_station_cache()
        stations = self._station_cache
        if state:
            stations = [s for s in stations if s.get("state") == state.upper()]
        percentiles = self._fetch_percentiles()
        return [self._enrich(s, percentiles) for s in stations]

    def get_station(self, station_number: str) -> Optional[dict]:
        try:
            raw = self._client.get_station(station_number)
            percentiles = self._fetch_percentiles()
            station_dict = self._station_to_dict(raw)
            return self._enrich(station_dict, percentiles, detail=True)
        except Exception as e:
            logger.warning(f"get_station {station_number} failed: {e}")
            return None

    def _refresh_station_cache(self):
        try:
            all_stations = []
            for state in PNW_STATES:
                page = self._client.get_stations(state=state, agency="USGS", limit=10000)
                for station in page.results:
                    d = self._station_to_dict(station)
                    # StreamflowOps does not echo a state field per record; stamp it
                    # from the known per-state query so list_stations() can filter.
                    if not d.get("state"):
                        d["state"] = state
                    all_stations.append(d)
            self._station_cache = all_stations
            self._station_cache_time = time.time()
        except Exception as e:
            logger.error(f"Station cache refresh failed: {e}")

    @staticmethod
    def _station_to_dict(station) -> dict:
        if isinstance(station, dict):
            return station
        return {
            "station_number": station.station_number,
            "name": station.name,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "state": station.state_code,
            "is_active": station.is_active,
            "huc_code": getattr(station, "huc_code", None),
            "basin": getattr(station, "basin_name", None),
            "years_of_record": getattr(station, "years_of_record", None),
            "record_start_date": str(getattr(station, "record_start_date", None) or ""),
        }

    @staticmethod
    def _enrich(station: dict, percentiles: dict, detail: bool = False) -> dict:
        pct = percentiles.get(station["station_number"], {})
        enriched = {
            **station,
            "current_discharge_cfs": pct.get("current_discharge", None),
            "percentile_rank": pct.get("percentile_rank", None),
            "condition_band": pct.get("band", None),
            "condition_label": band_to_label(pct.get("band", "")),
        }
        if not detail:
            enriched.pop("huc_code", None)
            enriched.pop("basin", None)
            enriched.pop("years_of_record", None)
            enriched.pop("record_start_date", None)
        return enriched


_service_instance: Optional[StreamflowService] = None


def get_streamflow_service() -> StreamflowService:
    global _service_instance
    if _service_instance is None:
        _service_instance = StreamflowService()
    return _service_instance

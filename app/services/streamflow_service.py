import time
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.config import get_settings
from app.services.forecast_service import station_has_forecast

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

# Mirrors the USGS dashboard's TARGET_STATES (Western US). BC is intentionally
# omitted: it requires agency=EC (Environment Canada), which is a separate
# multi-agency effort tracked as a follow-up.
TARGET_STATES = ["OR", "WA", "ID", "MT", "NV", "CA", "UT", "AZ", "CO"]

# StreamflowOps caps stations responses at 1000 rows/page regardless of `limit`.
_STATION_PAGE_SIZE = 1000


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
        # station_number -> ISO date string of last observation
        self._last_obs_cache: dict = {}
        self._last_obs_cache_time: float = 0.0

    def _stations_stale(self) -> bool:
        settings = get_settings()
        return (time.time() - self._station_cache_time) > settings.station_cache_ttl

    def _percentiles_stale(self) -> bool:
        return (time.time() - self._percentile_cache_time) > 1800  # 30 min

    def _last_obs_stale(self) -> bool:
        return (time.time() - self._last_obs_cache_time) > 3600  # 1 h

    def _fetch_last_obs(self) -> dict:
        # /stations/last-observation/ is the most stable freshness signal
        # StreamflowOps exposes (~10k stations). On upstream failure keep
        # the last good cache so the map never blanks.
        if not self._last_obs_stale():
            return self._last_obs_cache
        try:
            resp = self._client._request(
                "GET", "/api/v1/stations/last-observation/", params={}
            )
            rows = resp if isinstance(resp, list) else resp.get("results", [])
            new_map = {
                r["station_number"]: r.get("last_observation_date")
                for r in rows
                if r.get("station_number")
            }
            if new_map:
                self._last_obs_cache = new_map
                self._last_obs_cache_time = time.time()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"last-observation fetch failed: {e}")
        return self._last_obs_cache

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
        last_obs = self._fetch_last_obs()
        return [self._enrich(s, percentiles, last_obs=last_obs) for s in stations]

    def get_station(self, station_number: str) -> Optional[dict]:
        # Serve detail from the station cache (it already holds full per-
        # station fields). A live upstream call per detail open made the
        # endpoint slow/unreliable — StreamflowOps intermittently resets,
        # so most detail loads were 404ing after ~10s. Only fall back to a
        # live lookup for stations not in the cached region.
        if self._stations_stale():
            self._refresh_station_cache()
        percentiles = self._fetch_percentiles()
        last_obs = self._fetch_last_obs()
        for s in self._station_cache:
            if s.get("station_number") == station_number:
                return self._enrich(s, percentiles, detail=True, last_obs=last_obs)
        try:
            raw = self._client.get_station(station_number)
            station_dict = self._station_to_dict(raw)
            return self._enrich(station_dict, percentiles, detail=True, last_obs=last_obs)
        except Exception as e:
            logger.warning(f"get_station {station_number} failed: {e}")
            return None

    def _refresh_station_cache(self):
        # NOTE: the StreamflowOps /stations/ endpoint ignores the `offset`
        # query param (offset=0 and offset=1000 return the identical first
        # 1000 rows), so there is no usable pagination — 1000 stations/state
        # is a hard ceiling via this API. Full coverage would require direct
        # DB access (as the dashboard uses), which is out of scope here.
        # Each state is fetched independently so a transient failure on one
        # state cannot wipe coverage for the others.
        def fetch_state(state: str) -> list[dict]:
            # StreamflowOps connections reset intermittently; retry so a big
            # state (e.g. WA) isn't silently dropped from coverage.
            last_err = None
            for attempt in range(3):
                try:
                    page = self._client.get_stations(
                        state=state, agency="USGS",
                        limit=_STATION_PAGE_SIZE,
                    )
                    rows = []
                    for station in page.results:
                        d = self._station_to_dict(station)
                        # StreamflowOps does not echo a state field per
                        # record; stamp it from the known per-state query
                        # so list_stations() can filter.
                        if not d.get("state"):
                            d["state"] = state
                        rows.append(d)
                    return rows
                except Exception as e:  # noqa: BLE001 — retry any transient
                    last_err = e
            logger.warning(f"Station fetch failed for {state}: {last_err}")
            return []

        # States are independent fetches — run them concurrently to keep the
        # cold-cache refresh fast (sequential was ~35s for 9 states).
        all_stations: list[dict] = []
        any_success = False
        with ThreadPoolExecutor(max_workers=5) as pool:
            for rows in pool.map(fetch_state, TARGET_STATES):
                if rows:
                    any_success = True
                    all_stations.extend(rows)

        # Only replace the cache if at least one state succeeded, so a total
        # outage doesn't blow away a previously good cache.
        if any_success:
            self._station_cache = all_stations
            self._station_cache_time = time.time()
        else:
            logger.error("Station cache refresh failed: all states errored")

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
    def _enrich(
        station: dict,
        percentiles: dict,
        detail: bool = False,
        last_obs: Optional[dict] = None,
    ) -> dict:
        pct = percentiles.get(station["station_number"], {})
        enriched = {
            **station,
            "current_discharge_cfs": pct.get("current_discharge", None),
            "percentile_rank": pct.get("percentile_rank", None),
            "condition_band": pct.get("band", None),
            "condition_label": band_to_label(pct.get("band", "")),
            "has_forecast": station_has_forecast(station["station_number"]),
            "last_observation_date":
                (last_obs or {}).get(station["station_number"]),
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

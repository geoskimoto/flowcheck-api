import time
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import parse_qs, urlparse

from app.config import get_settings
from app.services.forecast_service import station_has_forecast

logger = logging.getLogger(__name__)

_WY_START_MONTH = 10


def _day_of_wy(d: datetime) -> int:
    """Day-of-water-year (Oct 1 = 1). Mirrors water_year_service helpers."""
    wy_start_year = d.year if d.month >= _WY_START_MONTH else d.year - 1
    wy_start = datetime(wy_start_year, _WY_START_MONTH, 1)
    return (d - wy_start).days + 1


def _interp_pct(qs: tuple, x: float) -> Optional[float]:
    """Estimate percentile rank from (q10, q25, q50, q75, q90) anchors."""
    anchors = list(zip((10, 25, 50, 75, 90), qs))
    if any(a is None for _, a in anchors):
        return None
    if x <= anchors[0][1]:
        if anchors[0][1] <= 0:
            return float(anchors[0][0])
        return max(0.0, anchors[0][0] * (x / anchors[0][1]))
    if x >= anchors[-1][1]:
        a, b = anchors[-2], anchors[-1]
        if b[1] == a[1]:
            return float(b[0])
        slope = (b[0] - a[0]) / (b[1] - a[1])
        return min(99.9, b[0] + slope * (x - b[1]))
    for i in range(len(anchors) - 1):
        a, b = anchors[i], anchors[i + 1]
        if a[1] <= x <= b[1]:
            if b[1] == a[1]:
                return float(a[0])
            ratio = (x - a[1]) / (b[1] - a[1])
            return a[0] + ratio * (b[0] - a[0])
    return None


def _pct_to_band(p: float) -> str:
    """Map a percentile rank to StreamflowOps' band labels."""
    cuts = (
        (5, "p0_4"), (11, "p5_10"), (26, "p11_25"), (51, "p26_50"),
        (76, "p51_75"), (86, "p76_85"), (91, "p86_90"), (96, "p91_95"),
        (99, "p96_98"),
    )
    for thresh, band in cuts:
        if p < thresh:
            return band
    return "p99_100"

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
        # station_number -> {percentile_rank, current_discharge, band}
        # — computed by us from a bulk discharge fetch + the persistent
        # water-year-stats cache (stable when StreamflowOps' percentile
        # pipeline degrades).
        self._computed_pct_cache: dict = {}
        self._computed_pct_cache_time: float = 0.0
        # Boot-strap caches from Postgres so an API restart doesn't need
        # a successful upstream call to serve the map (Option B3).
        self._load_caches_from_db()

    def _load_caches_from_db(self) -> None:
        try:
            from app.database import SessionLocal
            from app.models.station_cache import StationCache
        except Exception as e:  # noqa: BLE001
            logger.warning(f"station_cache import failed: {e}")
            return
        db = SessionLocal()
        try:
            # Filter out any orphan rows that lack metadata (defensive — a
            # buggy persist could leave name='' rows that would then 500
            # the response via the StationSummary state-is-str validator).
            rows = (
                db.query(StationCache)
                .filter(StationCache.name != "")
                .all()
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"load stations_cache from DB failed: {e}")
            db.close()
            return
        try:
            self._station_cache = [
                {
                    "station_number": r.station_number,
                    "name": r.name or "",
                    "state": r.state,
                    "latitude": r.latitude,
                    "longitude": r.longitude,
                    "is_active": bool(r.is_active),
                    "huc_code": r.huc_code,
                    "basin": r.basin,
                    "years_of_record": r.years_of_record,
                    "record_start_date": r.record_start_date or "",
                }
                for r in rows
            ]
            if self._station_cache:
                # Treat DB-loaded data as fresh enough to serve; TTL still
                # drives the next upstream refresh.
                self._station_cache_time = time.time()
            self._last_obs_cache = {
                r.station_number: r.last_observation_date
                for r in rows
                if r.last_observation_date
            }
            if self._last_obs_cache:
                self._last_obs_cache_time = time.time()
            logger.info(
                f"Loaded {len(self._station_cache)} stations "
                f"({len(self._last_obs_cache)} with last_observation_date) "
                f"from DB"
            )
        finally:
            db.close()

    def _persist_station_cache(self, stations: list[dict]) -> None:
        """Upsert station metadata. Leaves last_observation_date untouched
        so the separate last-obs refresh manages that column."""
        if not stations:
            return
        try:
            from datetime import datetime, timezone
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from app.database import SessionLocal
            from app.models.station_cache import StationCache
        except Exception as e:  # noqa: BLE001
            logger.warning(f"persist stations import failed: {e}")
            return
        now = datetime.now(timezone.utc)
        rows = [
            {
                "station_number": s["station_number"],
                "name": s.get("name") or "",
                "state": s.get("state"),
                "latitude": s.get("latitude"),
                "longitude": s.get("longitude"),
                "is_active": bool(s.get("is_active", True)),
                "huc_code": s.get("huc_code"),
                "basin": s.get("basin"),
                "years_of_record": s.get("years_of_record"),
                "record_start_date": s.get("record_start_date") or None,
                "refreshed_at": now,
            }
            for s in stations
            if s.get("station_number")
        ]
        if not rows:
            return
        db = SessionLocal()
        try:
            stmt = pg_insert(StationCache).values(rows)
            update_cols = {
                c: stmt.excluded[c]
                for c in (
                    "name", "state", "latitude", "longitude", "is_active",
                    "huc_code", "basin", "years_of_record",
                    "record_start_date", "refreshed_at",
                )
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["station_number"], set_=update_cols
            )
            db.execute(stmt)
            db.commit()
            logger.info(f"Persisted {len(rows)} stations to DB")
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.warning(f"persist stations failed: {e}")
        finally:
            db.close()

    def _persist_last_obs(self, latest: dict) -> None:
        """Update the last_observation_date column for stations we cover.

        Only updates existing rows — orphan stations from upstream's much
        larger last-observation feed (e.g. Canadian / out-of-region) would
        otherwise pollute the table with rows that have no metadata.
        """
        if not latest or not self._station_cache:
            return
        try:
            from datetime import datetime, timezone
            from sqlalchemy import text
            from app.database import SessionLocal
        except Exception as e:  # noqa: BLE001
            logger.warning(f"persist last_obs import failed: {e}")
            return
        covered = {s.get("station_number") for s in self._station_cache}
        now = datetime.now(timezone.utc)
        rows = [
            {"sn": sn, "lod": d, "ra": now}
            for sn, d in latest.items()
            if sn in covered
        ]
        if not rows:
            return
        db = SessionLocal()
        try:
            stmt = text(
                "UPDATE stations_cache "
                "SET last_observation_date = :lod, refreshed_at = :ra "
                "WHERE station_number = :sn"
            )
            db.execute(stmt, rows)
            db.commit()
            logger.info(
                f"Persisted last_observation_date for {len(rows)} stations"
            )
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.warning(f"persist last_obs failed: {e}")
        finally:
            db.close()

    def _stations_stale(self) -> bool:
        settings = get_settings()
        return (time.time() - self._station_cache_time) > settings.station_cache_ttl

    def _percentiles_stale(self) -> bool:
        return (time.time() - self._percentile_cache_time) > 1800  # 30 min

    def _last_obs_stale(self) -> bool:
        return (time.time() - self._last_obs_cache_time) > 3600  # 1 h

    def _computed_pct_stale(self) -> bool:
        return (time.time() - self._computed_pct_cache_time) > 1800  # 30 min

    def _fetch_latest_discharge(self) -> dict:
        """Bulk-fetch recent daily-mean observations across all stations,
        return {station_number: latest discharge value}. ~1 upstream call
        (+ pagination), much cheaper than 6k per-station fetches."""
        end = datetime.now().date()
        start = end - timedelta(days=5)
        endpoint = "/api/v1/observations/discharge/"
        params = {
            "type": "daily_mean",
            "start_date": str(start),
            "end_date": str(end),
            "limit": 1000,
        }
        latest: dict[str, tuple[str, float]] = {}
        pages = 0
        while endpoint and pages < 20:  # hard cap to bound work
            try:
                data = self._client._request("GET", endpoint, params=params)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"bulk discharge fetch failed: {e}")
                break
            for o in data.get("results", []):
                sn = o.get("station_number")
                d = o.get("discharge")
                t = o.get("observed_at")
                if not sn or d is None or t is None:
                    continue
                try:
                    dv = float(d)
                except (TypeError, ValueError):
                    continue
                prev = latest.get(sn)
                if prev is None or t > prev[0]:
                    latest[sn] = (t, dv)
            nxt = data.get("next")
            if not nxt:
                break
            parsed = urlparse(nxt)
            endpoint = parsed.path
            params = {
                k: v[0] if len(v) == 1 else v
                for k, v in parse_qs(parsed.query).items()
            }
            pages += 1
        return {sn: v[1] for sn, v in latest.items()}

    def _load_wy_cache(self) -> dict:
        """station_number -> {day_of_wy(int): (q10,q25,q50,q75,q90)} for the
        current water year. Loaded fresh whenever we recompute percentiles
        (cheap — small table; grows as the warm script runs)."""
        from app.database import SessionLocal
        from app.models.water_year_stats_cache import WaterYearStatsCache
        from app.services.water_year_service import _current_water_year
        wy = _current_water_year()
        out: dict[str, dict[int, tuple]] = {}
        db = SessionLocal()
        try:
            rows = (
                db.query(WaterYearStatsCache)
                .filter(WaterYearStatsCache.water_year == wy)
                .all()
            )
            for r in rows:
                sj = r.stats_json or []
                if not sj:
                    continue
                m: dict[int, tuple] = {}
                for s in sj:
                    dow = s.get("day_of_wy")
                    if dow is None:
                        continue
                    m[int(dow)] = (
                        s.get("q10"), s.get("q25"), s.get("q50"),
                        s.get("q75"), s.get("q90"),
                    )
                if m:
                    out[r.station_number] = m
        except Exception as e:  # noqa: BLE001
            logger.warning(f"WY cache load failed: {e}")
        finally:
            db.close()
        return out

    def _fetch_computed_percentiles(self) -> dict:
        """Compute current percentile per station ourselves. Stable when the
        upstream percentile-bands feed degrades; coverage grows with the
        warm script. Hybrid: callers should prefer this map, falling back
        to _fetch_percentiles for stations we can't compute."""
        if not self._computed_pct_stale():
            return self._computed_pct_cache
        discharge = self._fetch_latest_discharge()
        if not discharge:
            return self._computed_pct_cache
        wy = self._load_wy_cache()
        today_dowy = _day_of_wy(datetime.now())
        out: dict[str, dict] = {}
        for sn, x in discharge.items():
            stats = wy.get(sn)
            if not stats:
                continue
            qs = stats.get(today_dowy) or stats[
                min(stats, key=lambda k: abs(k - today_dowy))
            ]
            pct = _interp_pct(qs, x)
            if pct is None:
                continue
            out[sn] = {
                "percentile_rank": round(pct, 2),
                "current_discharge": x,
                "band": _pct_to_band(pct),
            }
        # last-good fallback: only swap in if we computed something
        if out:
            self._computed_pct_cache = out
            self._computed_pct_cache_time = time.time()
        return self._computed_pct_cache

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
                self._persist_last_obs(new_map)
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
        computed = self._fetch_computed_percentiles()
        return [
            self._enrich(s, percentiles, last_obs=last_obs, computed=computed)
            for s in stations
        ]

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
        computed = self._fetch_computed_percentiles()
        for s in self._station_cache:
            if s.get("station_number") == station_number:
                return self._enrich(s, percentiles, detail=True,
                                    last_obs=last_obs, computed=computed)
        try:
            raw = self._client.get_station(station_number)
            station_dict = self._station_to_dict(raw)
            return self._enrich(station_dict, percentiles, detail=True,
                                last_obs=last_obs, computed=computed)
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
            self._persist_station_cache(all_stations)
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
        computed: Optional[dict] = None,
    ) -> dict:
        # Hybrid: prefer our own computed percentile when available
        # (stable against StreamflowOps' brittle percentile-bands feed),
        # fall back to the upstream snapshot otherwise.
        sn = station["station_number"]
        pct = (computed or {}).get(sn) or percentiles.get(sn, {})
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

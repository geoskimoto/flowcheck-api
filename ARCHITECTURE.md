# FlowCheck / StreamCast — System Architecture

This document describes the full system: the mobile app (**StreamCast**),
the backend (**flowcheck-api**), and the upstream data source
(**StreamflowOps / DataOps API**) — how they fit together, why the backend
layer exists, and the internals of each component.

---

## 1. High-level overview

```
 ┌──────────────────┐   HTTPS + JWT      ┌────────────────────┐   HTTPS + Token   ┌────────────────────┐
 │  StreamCast app   │ ─────────────────▶ │   flowcheck-api    │ ────────────────▶ │   StreamflowOps     │
 │  (Flutter / iOS-  │                    │   (FastAPI BFF)    │                   │   DataOps REST API  │
 │   Android)        │ ◀───────────────── │                    │ ◀──────────────── │  (private upstream) │
 └──────────────────┘  clean app JSON     └─────────┬──────────┘   raw USGS data   └────────────────────┘
                                                     │
                              ┌──────────────────────┼───────────────────────┐
                              │                       │                       │
                       ┌──────┴──────┐        ┌───────┴────────┐      ┌───────┴────────┐
                       │ PostgreSQL  │        │ In-proc caches │      │ APScheduler +  │
                       │ (users,     │        │ (stations,     │      │ Firebase FCM   │
                       │  alerts,    │        │  percentiles,  │      │ (hourly flood  │
                       │  WY cache)  │        │  forecasts)    │      │  alert push)   │
                       └─────────────┘        └────────────────┘      └────────────────┘
```

- **StreamCast** talks **only** to flowcheck-api. It never sees StreamflowOps
  or its token.
- **flowcheck-api** is a **Backend-For-Frontend (BFF)**: it owns the app's
  product features (accounts, favorites, alerts, push), shapes/normalizes the
  messy upstream data, computes derived analytics, and shields clients from an
  unreliable upstream.
- **StreamflowOps** is a private REST API (shared with the separate
  `usgs-streamflow-dashboard` web app) that serves raw USGS streamflow data.

---

## 2. Why flowcheck-api exists (the BFF rationale)

It is **not** redundant plumbing. Removing it is not viable:

1. **Secret containment.** StreamflowOps requires a private
   `DATAOPS_API_TOKEN`. A mobile APK/IPA is trivially decompiled — shipping
   the token would expose the private upstream to the world. The token lives
   only server-side; the app authenticates to flowcheck-api with its own JWT
   user accounts.

2. **The app's product is not in StreamflowOps.** User registration/login,
   favorites/watchlist, flood-alert subscriptions, device registration, and
   push notifications all require a database and server logic. StreamflowOps
   is raw data only.

3. **Heavy data shaping & computation.** StreamflowOps' shape does not match
   what a client needs (see §5 for the full list of quirks). Water-year
   percentile bands must be computed from ~30 years of daily discharge with
   pandas — infeasible on a phone and would require shipping gigabytes of raw
   data per device. flowcheck-api does this once, server-side, cached.

4. **Resilience.** StreamflowOps resets connections constantly (an observed
   pre-warm pass failed 702/730 stations transiently). flowcheck-api adds
   caching, retries, per-state isolation, and a definitive-vs-transient
   error distinction so one warm server cache serves all users instead of
   every device independently hammering and failing.

5. **Stable contract.** The app depends on flowcheck-api's clean, versioned
   endpoints, not StreamflowOps' quirks. Upstream changes/bugs are fixed once
   server-side with no app re-release (most integration fixes to date needed
   zero app changes).

6. **Server-only work.** The hourly flood-alert check (poll subscriptions →
   percentile check → FCM push) inherently needs a always-on server.

---

## 3. Component: StreamCast (flowcheck-app)

Flutter mobile app for river recreationists. Repo: `flowcheck-app`
(SSH `git@github.com:geoskimoto/flowcheck-app.git`). Dart package
`streamcast`, Android package `com.StreamCast`.

### Tech stack
- **Flutter 3.41.9**
- **Riverpod** (`flutter_riverpod`) — state management (FutureProviders)
- **go_router** — navigation, `ShellRoute` with bottom-tab scaffold
- **flutter_map** + OpenStreetMap tiles + **flutter_map_marker_cluster** —
  the gauge map with clustered, condition-colored markers
- **fl_chart** — water-year percentile-band chart (note: use `barWidth`,
  not `strokeWidth`, on `LineChartBarData`)
- **Dio** — HTTP client with a JWT Bearer interceptor + auto-refresh on 401
- **firebase_core / firebase_messaging** — FCM push
- **flutter_secure_storage** — JWT token storage

### Structure (`lib/`)
```
core/
  api/api_client.dart            Dio wrapper: baseUrl from AppConfig,
                                 connectTimeout 15s, receiveTimeout 30s,
                                 JWT interceptor + refresh-on-401
  config.dart                    AppConfig.apiBaseUrl =
                                 String.fromEnvironment('API_BASE_URL',
                                   default 'https://flowcheck-api.3rdplaces.io')
  models/                        station, forecast, current_water_year,
                                 water_year_stat, auth_state
  providers/                     Riverpod providers (one per domain):
                                 stationsProvider, stationDetailProvider,
                                 waterYearStatsProvider, currentWaterYearProvider,
                                 forecastProvider, favoritesProvider,
                                 alertsProvider, authProvider, apiClientProvider
  router/                        go_router config + bottom-nav shell
  services/notification_service  FCM token registration + handlers
  theme/app_theme.dart           dark theme + Okabe-Ito conditionColor()
features/
  map/                           map_screen (search + filter + clustering),
                                 station_bottom_sheet
  station/                       station_screen (header, chart, footer),
                                 widgets/water_year_chart (bands, median,
                                 forecast, current-WY line, legend)
  watchlist/ alerts/ settings/ auth/
main.dart                        Firebase init + ProviderScope
```

### Map condition colors (Okabe-Ito, colorblind-safe)
Derived client-side from `percentile_rank`: `<25` low (sky blue),
`<75` normal (teal), `<95` elevated (amber), `≥95` flood (vermilion),
`null` unknown (grey).

### API target switch (no code change)
`AppConfig.apiBaseUrl` is a compile-time `String.fromEnvironment`:
- **Deployed:** `flutter build apk --debug` (no dart-define) → uses the
  production default `https://flowcheck-api.3rdplaces.io`.
- **Local dev:** `flutter build apk --debug --dart-define=API_BASE_URL=http://localhost:8098`
  plus `adb -s <device> reverse tcp:8098 tcp:8098` (a physical phone cannot
  reach the laptop's `localhost` or the emulator-only `10.0.2.2` without the
  reverse tunnel).

---

## 4. Component: flowcheck-api

FastAPI backend. Repo: `flowcheck-api`. Port **8098** locally; deployed at
`https://flowcheck-api.3rdplaces.io`.

### Key decisions
- **bcrypt directly** (NOT passlib — passlib 1.7.x is incompatible with
  bcrypt 4.x)
- **python-jose** JWT — access token 30 min, refresh token 30 days
- **pydantic-settings** for config from `.env`
- **APScheduler** runs the hourly flood check inside the FastAPI lifespan
- **SQLAlchemy 2.x + Alembic** over PostgreSQL 16+

### Routers (`app/routers/`) → HTTP surface
| Router | Endpoints | Notes |
|---|---|---|
| `auth` | `POST /auth/register`, `/auth/login`, `/auth/refresh`, `DELETE /auth/account` | JWT issue/refresh; bcrypt |
| `stations` | `GET /stations/`, `GET /stations/{id}`, `GET /stations/{id}/water-year-stats`, `GET /stations/{id}/current-water-year`, `GET /stations/{id}/forecast` | the core data surface |
| `favorites` | `GET/POST /favorites/`, `DELETE /favorites/{station_number}` | per-user watchlist |
| `alerts` | `GET/POST /alerts/subscriptions/`, `DELETE /alerts/subscriptions/{station_number}`, `GET /alerts/history/` | flood-alert subscriptions + event history |
| `devices` | `POST /devices/register` | FCM device token registration |
| (app) | `GET /health` | liveness |

### Services (`app/services/`) — where the logic lives
- **`streamflow_service.py`** — the StreamflowOps integration for stations &
  percentiles.
  - `TARGET_STATES = OR,WA,ID,MT,NV,CA,UT,AZ,CO` (mirrors the dashboard's
    Western-US coverage; BC omitted — needs agency=EC, a future multi-agency
    effort).
  - `_refresh_station_cache()` — fetches all states **concurrently**
    (`ThreadPoolExecutor`, 3× retry per state), stamps `state` onto each
    record (upstream doesn't return it), keeps a good cache if some states
    fail. In-memory cache, TTL `station_cache_ttl` (default 30 min).
  - `_fetch_percentiles()` — pulls the separate percentile-bands endpoint,
    keyed by station_number; 30-min cache.
  - `list_stations(state=)` / `get_station(id)` — `get_station` serves from
    the station cache (a live per-detail upstream call previously caused
    7–10 s timeouts → 404s; cache makes it ~1 ms). Falls back to a live
    lookup only for out-of-region stations.
  - `_enrich()` joins station + percentile + condition label
    (`BAND_LABELS`, incl. the fine high-end bands p76_85…p99_100).
- **`water_year_service.py`** — derived analytics.
  - `get_water_year_stats(id, db)` — returns per-day-of-WY percentile bands
    (q10/q25/q50/q75/q90/mean) computed via pandas from ~30 yr of daily
    discharge. DB-cached (`water_year_stats_cache`, valid for the whole
    water year, invalidates Oct 1). **Definitive empty result (insufficient
    history) is cached as `[]`** so a no-data station is an instant repeat
    instead of a repeated slow fetch.
  - `get_current_water_year_series(id)` — the in-progress water year's
    observed daily discharge as `[{day_of_wy, discharge}]` (small Oct-1→today
    fetch).
  - `_get_station_data_with_retry()` — 3× retry through StreamflowOps
    resets; raises `WaterYearDataUnavailable` (→ HTTP 503, **uncached**) for
    transient failure vs `[]` (→ HTTP 404) for genuine no-data. This
    distinction drives accurate app messaging ("no historical data" vs
    "temporarily unavailable — retry").
- **`forecast_service.py`** — NWRFC forecast retrieval.
  - StreamflowOps' forecast endpoint is keyed by **NWRFC code**, and there
    is **no USGS↔NWRFC crosswalk** in StreamflowOps. A bundled 239-entry map
    `app/data/usgs_nwrfc_map.json` (sourced from the dashboard's resid-cast
    config) does the translation. Unmapped station → 404 (graceful: app just
    shows no forecast line).
  - Per-station 3-hour cache with **last-good fallback** (the forecast
    endpoint is also slow/reset-prone).
- **`auth_service.py`** — bcrypt hashing, JWT encode/decode.
- **`notification_service.py`** — Firebase Admin FCM send.

### Data models (`app/models/`) → PostgreSQL tables
`users`, `devices`, `favorite_stations`, `alert_subscriptions`,
`alert_events`, `water_year_stats_cache` (+ `alembic_version`).
- `users` — account + bcrypt password hash
- `devices` — FCM tokens per user
- `favorite_stations` — watchlist (user × station_number)
- `alert_subscriptions` — which stations a user wants flood alerts for
- `alert_events` — fired alerts; `resolved_at` gates re-firing
- `water_year_stats_cache` — JSONB per-day-of-WY stats, keyed by
  station_number + water_year

### Schemas (`app/schemas/`)
Pydantic request/response models: `station` (StationSummary/StationDetail),
`forecast` (ForecastResponse/ForecastPoint), `auth`, `favorite`, `alert`.

### Configuration (`.env`, via pydantic-settings)
| Var | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | JWT signing key |
| `DATAOPS_API_URL` | StreamflowOps base URL |
| `DATAOPS_API_TOKEN` | StreamflowOps bearer/token (the secret the app must never see) |
| `FIREBASE_CREDENTIALS_PATH` | Firebase service-account JSON (FCM send) |

`.env` / `.env.test` are gitignored. Alembic's `env.py` falls back to app
settings (so it reads `.env`) when `DATABASE_URL` is not in the OS env.

### Flood-alert scheduler
APScheduler runs hourly inside the FastAPI lifespan:
1. Load active `alert_subscriptions` (unique station_numbers).
2. Query StreamflowOps percentile-bands.
3. If `percentile_rank ≥ 95` and no open `alert_event` → insert event +
   send FCM to the user's devices.
4. If an open event and `percentile_rank < 90` → set `resolved_at` (gate
   reset, so it can fire again later).

---

## 5. Component: StreamflowOps (DataOps API) — contract & quirks

Base: `https://streamflowops.3rdplaces.io`. Auth: `Authorization: Token
<DATAOPS_API_TOKEN>`. Shared with the `usgs-streamflow-dashboard` web app.

Endpoints flowcheck-api uses:
- `GET /api/v1/stations/?state=&agency=USGS` — station metadata
- `GET /api/v1/observations/discharge/` — daily-mean / realtime obs
  (`station_number`, `start_date`, `end_date`, `type`)
- `GET /api/v1/observations/discharge/percentile-bands/` — current
  percentile per station
- `GET /api/v1/forecasts/by-station/{nwrfc_code}/` + `/api/v1/forecasts/{id}/`
  — NWRFC/CHPS forecast runs + points

**Hard-won quirks (why the service layer is non-trivial):**
- **`offset` pagination is ignored** — `offset=0` and `offset=1000` return
  the identical first 1000 rows. There is **no usable pagination**;
  effectively a **1000 stations/state ceiling** via this API. (The dashboard
  gets more via direct DB access, which flowcheck-api does not have.)
- **No per-record `state` field** on station objects — flowcheck-api stamps
  it from the per-state query.
- **No USGS↔NWRFC crosswalk** — forecasts are keyed by NWRFC code; the
  bundled map handles ~239 stations only.
- **Percentile bands are a separate endpoint** from station metadata and use
  finer high-end bands (`p76_85 … p99_100`) than originally assumed.
- **Discharge observations** use `observed_at` (tz-aware) + `discharge`
  (string); fields/keys differ from intuition (the dataops client model maps
  them to `observed_at` / `discharge_value`).
- **Frequent connection resets / timeouts.** This is the dominant
  reliability constraint. A full cold pre-warm is only ~4% effective per
  pass against this instability.

The HTTP client lives in `dataops_client/` (vendored).

---

## 6. End-to-end data flows

**Map load** — `App GET /stations/` → flowcheck-api serves the enriched
station cache (refreshing per-state from StreamflowOps if stale, joined with
percentile bands) → app renders clustered, condition-colored markers; search
& filters are client-side over this list.

**Station detail** — `App GET /stations/{id}` → served from the station
cache (no upstream call) → ~1 ms.

**Water-year chart** — `App GET /stations/{id}/water-year-stats` →
flowcheck-api checks `water_year_stats_cache`; **hit** → instant; **miss** →
fetch ~30 yr daily discharge from StreamflowOps (retry through resets),
compute percentiles with pandas, cache, return; `404` = no/insufficient
history (cached), `503` = transient (retryable). In parallel the app calls
`/current-water-year` (observed in-progress line) and `/forecast` (NWRFC
overlay, mapped stations only).

**Flood alert** — hourly server job (see §4) → FCM push to the user's
devices when a subscribed station crosses the 95th-percentile threshold.

---

## 7. Environments & deployment

| | Local dev | Deployed |
|---|---|---|
| flowcheck-api | `uvicorn app.main:app --port 8098` | `flowcheck-api.3rdplaces.io` |
| App points at it via | `--dart-define=API_BASE_URL=http://localhost:8098` + `adb reverse` | default base URL (no dart-define) |
| DB | local PostgreSQL `flowcheck_db` (`flowcheck_test_db` for tests) | server PostgreSQL |

- Migrations: `alembic upgrade head`.
- Tests: `pytest tests/` (mocked; needs `flowcheck_test_db` + `.env.test`).
  "Never modify application code to make a failing test pass."
- Cache pre-warm: `./venv/bin/python scripts/warm_stats_cache.py [--state OR]
  [--limit N]` — populates `water_year_stats_cache`; idempotent (cache hits
  skip fast; transient failures retried next run).

---

## 8. Known limitations

- **Reliability ceiling is StreamflowOps**, not flowcheck-api. Cold
  water-year / current-WY / forecast calls will intermittently be slow or
  return 503 because the upstream resets connections constantly. Mitigations:
  caching (DB + in-proc + last-good), retries, the 404/503 split, and the
  app's "temporarily unavailable — Retry" UX. Pre-warming helps but is only
  partially effective per pass.
- **~1000 stations/state ceiling** (upstream offset bug) — full parity with
  the dashboard's larger coverage would require direct DB access.
- **BC / non-USGS agencies** not covered (needs agency=EC support).
- **Forecasts** limited to the ~239 NWRFC-mapped stations.
- The app repo's bundled `CLAUDE.md` "Dev Environment" section is stale
  (describes an old VMware VM, wrong API port `8052`); this document and the
  flowcheck-api `CLAUDE.md` are authoritative.

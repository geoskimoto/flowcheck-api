# flowcheck-api — Claude Context

## What This Is
FastAPI backend for the FlowCheck mobile app. Proxies StreamflowOps API (USGS streamflow data),
adds JWT auth, user favorites, alert subscriptions, and sends FCM push notifications when
flow at a subscribed station reaches the 95th percentile.

## Port & Deploy
- Port **8052** (8050=dashboard, 8051=percent-runoff, 8001=resid-cast)
- Systemd service: `sudo systemctl restart flowcheck-api`
- Unit file: `/home/geoskimoto/projects/flowcheck-api/flowcheck-api.service`
- Nginx config: `/home/geoskimoto/projects/flowcheck-api/flowcheck-api.3rdplaces.io.conf`
  → copy to `/etc/nginx/sites-enabled/` and reload nginx

## Database
- PostgreSQL 16, `flowcheck_db`, user `flowcheck_user`
- Test DB: `flowcheck_test_db` (same user)
- Migrations: `alembic upgrade head`
- Tables: users, devices, favorite_stations, alert_subscriptions, alert_events, water_year_stats_cache

## Virtualenv
```bash
source /home/geoskimoto/projects/flowcheck-api/venv/bin/activate
```

## Running Tests
```bash
cd /home/geoskimoto/projects/flowcheck-api
source venv/bin/activate
pytest tests/ -v
```
All 46 tests should pass. **Never modify application code to make a failing test pass.**

## Key Architecture Decisions
- **bcrypt directly** (NOT passlib) — passlib 1.7.x is incompatible with bcrypt 4.x
- **python-jose** for JWT (access token 30 min, refresh token 30 days)
- **APScheduler** runs hourly flood check in the FastAPI lifespan context manager
- **Water year stats** are computed server-side from raw historical discharge data, cached
  in `water_year_stats_cache` table (JSONB), invalidated Oct 1 each water year
- **StreamflowOps cache**: station list cached 30 min, percentile data cached 30 min
- **Flood threshold**: ≥95th percentile triggers FCM; recovery gate at <90th percentile

## Flood Alert Logic
1. Hourly job fetches all active `alert_subscriptions` (unique station_numbers)
2. Calls StreamflowOps `GET /api/v1/observations/discharge/percentile-bands/`
3. If `percentile_rank >= 95.0` AND no open `alert_event` (resolved_at IS NULL) → insert event + send FCM
4. If open event and `percentile_rank < 90.0` → set `resolved_at = now()` (resets gate)

## Environment Variables (.env)
- `DATABASE_URL` — PostgreSQL connection string
- `SECRET_KEY` — JWT signing key (real secret, already set)
- `DATAOPS_API_TOKEN` — StreamflowOps API token (copied from dashboard project)
- `FIREBASE_CREDENTIALS_PATH` — path to Firebase service account JSON
  → **STILL NEEDS**: actual `firebase-credentials.json` file from Firebase console

## StreamflowOps API
- Base URL: `https://streamflowops.3rdplaces.io`
- Auth: `Authorization: Token <DATAOPS_API_TOKEN>`
- Stations: `GET /api/v1/stations/?state=WA&agency=USGS`
- Percentiles: `GET /api/v1/observations/discharge/percentile-bands/`

## Condition Levels
| Band | Label | ConditionLevel |
|---|---|---|
| p0_4, p5_10, p11_25 | Very Low / Low / Below Normal | low |
| p26_50, p51_75 | Normal / Above Normal | normal |
| p76_100 | High | elevated |
| ≥95th percentile | Flood | flood |

## What's NOT Done Yet
- `firebase-credentials.json` needs to be downloaded from Firebase console and placed at
  `FIREBASE_CREDENTIALS_PATH` path, then API restarted
- DNS record for `flowcheck-api.3rdplaces.io` needs to point to VPS
- SSL cert: `sudo clpctl lets-encrypt:install:certificate --domainName=flowcheck-api.3rdplaces.io`
- Systemd service has not been enabled/started yet (awaiting DNS+SSL)

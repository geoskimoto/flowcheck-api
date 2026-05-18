"""
Pre-warm the water_year_stats_cache table so the mobile app's chart loads
are instant DB hits instead of slow/flaky cold computes.

Run from the repo root with the venv (loads .env via app.config):

    ./venv/bin/python scripts/warm_stats_cache.py            # all cached stations
    ./venv/bin/python scripts/warm_stats_cache.py --limit 50 # first 50 (smoke test)
    ./venv/bin/python scripts/warm_stats_cache.py --state OR  # one state

Idempotent: stations already cached for the current water year are skipped
fast (cache HIT). Transiently-failed stations are left uncached and will be
retried on the next run.
"""
import argparse
import logging
import sys
from pathlib import Path

# Allow running as `./venv/bin/python scripts/warm_stats_cache.py` (Python
# puts scripts/ on sys.path[0], not the repo root, so `app` isn't importable).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.services.streamflow_service import get_streamflow_service  # noqa: E402
from app.services.water_year_service import (  # noqa: E402
    WaterYearDataUnavailable,
    get_water_year_stats,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
log = logging.getLogger("warm_stats_cache")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap number of stations")
    ap.add_argument("--state", default=None, help="restrict to one state (e.g. OR)")
    args = ap.parse_args()

    svc = get_streamflow_service()
    stations = svc.list_stations(state=args.state)
    nums = [s["station_number"] for s in stations]
    if args.limit:
        nums = nums[: args.limit]

    total = len(nums)
    ok = empty = transient = 0
    print(f"Warming {total} stations (state={args.state or 'ALL'})...")

    db = SessionLocal()
    try:
        for i, sn in enumerate(nums, 1):
            try:
                stats = get_water_year_stats(sn, db)
                if stats:
                    ok += 1
                else:
                    empty += 1  # cached "insufficient history"
            except WaterYearDataUnavailable:
                transient += 1  # left uncached; retry on a later run
            except Exception as e:  # noqa: BLE001
                transient += 1
                log.warning(f"{sn}: {e}")
            if i % 25 == 0 or i == total:
                print(f"  {i}/{total}  ok={ok} no-data={empty} transient={transient}")
    finally:
        db.close()

    print(f"Done. cached-with-data={ok} cached-no-data={empty} "
          f"transient-skipped={transient}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

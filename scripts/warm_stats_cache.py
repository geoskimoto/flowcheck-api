"""
Pre-warm the water_year_stats_cache table so the mobile app's chart loads
are instant DB hits instead of slow/flaky cold computes.

Run from the repo root with the venv (loads .env via app.config):

    ./venv/bin/python scripts/warm_stats_cache.py            # all stations
    ./venv/bin/python scripts/warm_stats_cache.py --limit 50 # first 50 (smoke test)
    ./venv/bin/python scripts/warm_stats_cache.py --state OR  # one state

Idempotent: stations already cached for the current water year are skipped
fast (cache HIT). Transiently-failed stations are left uncached and will be
retried on the next run. Same logic also runs nightly inside the API via
app/scheduler/cache_warmer.run_cache_warm (Option B2).
"""
import argparse
import logging
import sys
from pathlib import Path

# Allow running as `./venv/bin/python scripts/warm_stats_cache.py` — Python
# puts scripts/ on sys.path[0], not the repo root, so `app` isn't importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scheduler.cache_warmer import warm_water_year_cache  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap number of stations")
    ap.add_argument("--state", default=None, help="restrict to one state (e.g. OR)")
    ap.add_argument("--max-seconds", type=int, default=0,
                    help="stop after this many seconds (0 = no cap)")
    ap.add_argument("--prefer-recent-days", type=int, default=14,
                    help="warm recently-reporting stations first")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    result = warm_water_year_cache(
        state=args.state,
        limit=args.limit or None,
        max_seconds=args.max_seconds or None,
        prefer_recent_days=args.prefer_recent_days,
    )
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())

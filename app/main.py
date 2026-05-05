import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from app.routers import auth, stations, favorites, alerts, devices

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _run_alert_check_safe,
        trigger="interval",
        hours=1,
        id="flood_alert_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("APScheduler started — flood alert check every 1 hour")
    yield
    scheduler.shutdown(wait=False)
    logger.info("APScheduler stopped")


def _run_alert_check_safe():
    try:
        from app.scheduler.alert_checker import run_alert_check
        run_alert_check()
    except Exception as e:
        logger.error(f"Alert check job crashed: {e}", exc_info=True)


app = FastAPI(title="FlowCheck API", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(stations.router)
app.include_router(favorites.router)
app.include_router(alerts.router)
app.include_router(devices.router)


@app.get("/health")
def health():
    return {"status": "ok"}

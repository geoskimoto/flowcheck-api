import logging
from datetime import datetime, timezone
from typing import Optional

from app.database import SessionLocal
from app.models.alert_subscription import AlertSubscription
from app.models.alert_event import AlertEvent
from app.models.device import Device
from app.services.notification_service import send_fcm_notification

logger = logging.getLogger(__name__)

FLOOD_THRESHOLD = 95.0
RECOVERY_THRESHOLD = 90.0


def fetch_current_percentiles() -> dict:
    """Fetch current percentile data for all stations from StreamflowOps."""
    from app.config import get_settings
    from dataops_client.client import DataOpsClient
    settings = get_settings()
    client = DataOpsClient(
        base_url=settings.dataops_api_url,
        api_token=settings.dataops_api_token,
        timeout=settings.dataops_timeout,
    )
    resp = client._request("GET", "/api/v1/observations/discharge/percentile-bands/", params={"days_back": 2})
    return {
        r["station_number"]: {
            "percentile_rank": r.get("percentile_rank", 0.0),
            "current_discharge": r.get("current_discharge", 0.0),
            "band": r.get("band", ""),
        }
        for r in resp.get("results", [])
    }


def run_alert_check():
    """
    Hourly job: check all subscribed stations against flood threshold.
    - Sends FCM if percentile >= 95 and no open alert event exists.
    - Resolves open events when percentile drops below 90 (reset gate).
    """
    db = SessionLocal()
    try:
        subscriptions = db.query(AlertSubscription).filter(AlertSubscription.active == True).all()
        if not subscriptions:
            return

        try:
            percentiles = fetch_current_percentiles()
        except Exception as e:
            logger.error(f"Alert check aborted — could not fetch percentiles: {e}")
            return

        station_to_users: dict[str, list[str]] = {}
        for sub in subscriptions:
            station_to_users.setdefault(sub.station_number, []).append(sub.user_id)

        for station_number, user_ids in station_to_users.items():
            pct_data = percentiles.get(station_number)
            if not pct_data:
                continue

            rank = pct_data["percentile_rank"]
            cfs = pct_data["current_discharge"]

            if rank >= FLOOD_THRESHOLD:
                open_events = db.query(AlertEvent).filter(
                    AlertEvent.station_number == station_number,
                    AlertEvent.resolved_at == None,
                ).all()

                if not open_events:
                    event = AlertEvent(station_number=station_number, percentile_rank=rank)
                    db.add(event)
                    db.commit()

                    devices = db.query(Device).filter(Device.user_id.in_(user_ids)).all()
                    for device in devices:
                        send_fcm_notification(
                            fcm_token=device.fcm_token,
                            station_number=station_number,
                            river_name=station_number,
                            cfs=cfs,
                            percentile=rank,
                        )
                    logger.info(f"Flood alert dispatched: {station_number} at {rank:.1f}th pct to {len(devices)} devices")

            elif rank < RECOVERY_THRESHOLD:
                open_event = db.query(AlertEvent).filter(
                    AlertEvent.station_number == station_number,
                    AlertEvent.resolved_at == None,
                ).first()
                if open_event:
                    open_event.resolved_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.info(f"Alert resolved: {station_number} dropped to {rank:.1f}th pct")

    except Exception as e:
        logger.error(f"Alert check job failed: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

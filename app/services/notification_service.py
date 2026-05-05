import logging
from typing import Optional

logger = logging.getLogger(__name__)

_firebase_app = None


def _get_firebase_app():
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app
    try:
        import firebase_admin
        from firebase_admin import credentials
        from app.config import get_settings
        settings = get_settings()
        if not settings.firebase_credentials_path:
            logger.warning("FIREBASE_CREDENTIALS_PATH not set — push notifications disabled")
            return None
        cred = credentials.Certificate(settings.firebase_credentials_path)
        _firebase_app = firebase_admin.initialize_app(cred)
    except Exception as e:
        logger.error(f"Firebase init failed: {e}")
    return _firebase_app


def send_fcm_notification(fcm_token: str, station_number: str, river_name: str, cfs: float, percentile: float) -> bool:
    """Send a flood alert push notification. Returns True on success."""
    try:
        from firebase_admin import messaging
        _get_firebase_app()
        message = messaging.Message(
            notification=messaging.Notification(
                title=f"Flood Alert: {river_name}",
                body=f"Flow at {cfs:,.0f} CFS ({percentile:.0f}th percentile) — above flood threshold",
            ),
            data={
                "station_number": station_number,
                "percentile_rank": str(percentile),
                "current_cfs": str(cfs),
                "type": "flood_alert",
            },
            token=fcm_token,
        )
        messaging.send(message)
        logger.info(f"FCM sent: {station_number} → {fcm_token[:8]}...")
        return True
    except Exception as e:
        logger.error(f"FCM send failed for {fcm_token[:8]}...: {e}")
        return False

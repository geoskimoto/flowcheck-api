import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock


def _make_subscription(user_id, station_number, active=True):
    sub = MagicMock()
    sub.user_id = user_id
    sub.station_number = station_number
    sub.active = active
    return sub


def _make_device(user_id, fcm_token="test-token", platform="android"):
    dev = MagicMock()
    dev.user_id = user_id
    dev.fcm_token = fcm_token
    return dev


class TestAlertChecker:
    def test_sends_fcm_when_above_threshold(self):
        from app.scheduler.alert_checker import run_alert_check

        mock_db = MagicMock()
        subscriptions = [_make_subscription("user1", "14211720")]
        devices = [_make_device("user1", "token-abc")]

        mock_db.query.return_value.filter.return_value.all.side_effect = [
            subscriptions,   # active subscriptions query
            [],              # open alert_events query (no open event)
            devices,         # devices for subscribed users
        ]

        percentile_data = {
            "14211720": {"percentile_rank": 97.0, "current_discharge": 55000.0, "band": "p76_100"}
        }

        with patch("app.scheduler.alert_checker.fetch_current_percentiles", return_value=percentile_data):
            with patch("app.scheduler.alert_checker.send_fcm_notification") as mock_fcm:
                with patch("app.scheduler.alert_checker.SessionLocal", return_value=mock_db):
                    run_alert_check()

        mock_fcm.assert_called_once()
        kwargs = mock_fcm.call_args.kwargs
        assert kwargs["fcm_token"] == "token-abc"
        assert kwargs["station_number"] == "14211720"

    def test_suppresses_duplicate_alert(self):
        from app.scheduler.alert_checker import run_alert_check

        mock_db = MagicMock()
        open_event = MagicMock()
        open_event.resolved_at = None
        subscriptions = [_make_subscription("user1", "14211720")]

        mock_db.query.return_value.filter.return_value.all.side_effect = [
            subscriptions,
            [open_event],   # open event already exists — should suppress
        ]

        percentile_data = {
            "14211720": {"percentile_rank": 97.0, "current_discharge": 55000.0, "band": "p76_100"}
        }

        with patch("app.scheduler.alert_checker.fetch_current_percentiles", return_value=percentile_data):
            with patch("app.scheduler.alert_checker.send_fcm_notification") as mock_fcm:
                with patch("app.scheduler.alert_checker.SessionLocal", return_value=mock_db):
                    run_alert_check()

        mock_fcm.assert_not_called()

    def test_resolves_alert_when_below_recovery_threshold(self):
        from app.scheduler.alert_checker import run_alert_check

        mock_db = MagicMock()
        open_event = MagicMock()
        open_event.station_number = "14211720"
        open_event.resolved_at = None
        subscriptions = [_make_subscription("user1", "14211720")]

        mock_db.query.return_value.filter.return_value.all.side_effect = [
            subscriptions,
            [],             # no open event at threshold check
        ]
        mock_db.query.return_value.filter.return_value.first.return_value = open_event

        percentile_data = {
            "14211720": {"percentile_rank": 85.0, "current_discharge": 40000.0, "band": "p76_100"}
        }

        with patch("app.scheduler.alert_checker.fetch_current_percentiles", return_value=percentile_data):
            with patch("app.scheduler.alert_checker.send_fcm_notification") as mock_fcm:
                with patch("app.scheduler.alert_checker.SessionLocal", return_value=mock_db):
                    run_alert_check()

        mock_fcm.assert_not_called()
        assert open_event.resolved_at is not None

    def test_no_notification_when_below_threshold(self):
        from app.scheduler.alert_checker import run_alert_check

        mock_db = MagicMock()
        subscriptions = [_make_subscription("user1", "14211720")]
        mock_db.query.return_value.filter.return_value.all.side_effect = [subscriptions, []]

        percentile_data = {
            "14211720": {"percentile_rank": 60.0, "current_discharge": 20000.0, "band": "p51_75"}
        }

        with patch("app.scheduler.alert_checker.fetch_current_percentiles", return_value=percentile_data):
            with patch("app.scheduler.alert_checker.send_fcm_notification") as mock_fcm:
                with patch("app.scheduler.alert_checker.SessionLocal", return_value=mock_db):
                    run_alert_check()

        mock_fcm.assert_not_called()

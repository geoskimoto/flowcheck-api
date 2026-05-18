import pytest
from unittest.mock import patch, MagicMock


MOCK_FORECAST = {
    "station_number": "14187500",
    "nwrfc_code": "WTLO3",
    "source": "NOAA_RFC",
    "run_date": "2026-05-18T10:30:25Z",
    "points": [
        {"date": "2026-05-18T00:00:00Z", "value": 1180.0},
        {"date": "2026-05-18T06:00:00Z", "value": 1170.0},
    ],
}


@pytest.fixture()
def mock_forecast_service():
    with patch("app.routers.stations.get_forecast_service") as mock_factory:
        svc = MagicMock()
        mock_factory.return_value = svc
        yield svc


def test_forecast_returns_200(client, mock_forecast_service):
    mock_forecast_service.get_forecast.return_value = MOCK_FORECAST
    resp = client.get("/stations/14187500/forecast")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nwrfc_code"] == "WTLO3"
    assert data["source"] == "NOAA_RFC"
    assert len(data["points"]) == 2
    assert data["points"][0]["value"] == 1180.0


def test_forecast_404_when_unavailable(client, mock_forecast_service):
    mock_forecast_service.get_forecast.return_value = None
    resp = client.get("/stations/99999999/forecast")
    assert resp.status_code == 404


def test_forecast_passes_station_number(client, mock_forecast_service):
    mock_forecast_service.get_forecast.return_value = MOCK_FORECAST
    client.get("/stations/14187500/forecast")
    mock_forecast_service.get_forecast.assert_called_once_with("14187500")

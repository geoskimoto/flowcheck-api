import pytest
from unittest.mock import patch, MagicMock


MOCK_STATIONS = [
    {
        "station_number": "14211720",
        "name": "Willamette River at Portland",
        "latitude": 45.52,
        "longitude": -122.67,
        "state": "OR",
        "is_active": True,
        "current_discharge_cfs": 42000.0,
        "percentile_rank": 82.4,
        "condition_band": "p76_100",
        "condition_label": "High",
    },
    {
        "station_number": "12301933",
        "name": "Columbia River at Vancouver",
        "latitude": 45.62,
        "longitude": -122.65,
        "state": "WA",
        "is_active": True,
        "current_discharge_cfs": 180000.0,
        "percentile_rank": 55.0,
        "condition_band": "p51_75",
        "condition_label": "Above Normal",
    },
]

MOCK_STATION_DETAIL = {
    **MOCK_STATIONS[0],
    "huc_code": "17090010",
    "basin": "Willamette",
    "years_of_record": 80,
    "record_start_date": "1940-01-01",
}


@pytest.fixture()
def mock_streamflow_service():
    with patch("app.routers.stations.get_streamflow_service") as mock_factory:
        svc = MagicMock()
        svc.list_stations.return_value = MOCK_STATIONS
        svc.get_station.return_value = MOCK_STATION_DETAIL
        mock_factory.return_value = svc
        yield svc


def test_list_stations_returns_200(client, mock_streamflow_service):
    resp = client.get("/stations/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_list_stations_has_required_fields(client, mock_streamflow_service):
    resp = client.get("/stations/")
    station = resp.json()[0]
    for field in ("station_number", "name", "latitude", "longitude", "condition_band", "condition_label", "percentile_rank"):
        assert field in station, f"Missing field: {field}"


def test_list_stations_state_filter(client, mock_streamflow_service):
    resp = client.get("/stations/?state=OR")
    assert resp.status_code == 200
    mock_streamflow_service.list_stations.assert_called_once_with(state="OR")


def test_get_station_returns_200(client, mock_streamflow_service):
    resp = client.get("/stations/14211720")
    assert resp.status_code == 200
    data = resp.json()
    assert data["station_number"] == "14211720"


def test_get_station_not_found(client, mock_streamflow_service):
    mock_streamflow_service.get_station.return_value = None
    resp = client.get("/stations/XXXXXXXX")
    assert resp.status_code == 404


def test_condition_label_mapping():
    from app.services.streamflow_service import band_to_label
    assert band_to_label("p0_4") == "Very Low"
    assert band_to_label("p5_10") == "Low"
    assert band_to_label("p11_25") == "Below Normal"
    assert band_to_label("p26_50") == "Normal"
    assert band_to_label("p51_75") == "Above Normal"
    assert band_to_label("p76_100") == "High"
    assert band_to_label("unknown") == "Unknown"

import json
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from datetime import date


def _make_discharge_df(n_years=5) -> pd.DataFrame:
    """Generate synthetic daily mean discharge data for testing."""
    dates = pd.date_range("2018-10-01", "2023-09-30", freq="D")
    rng = np.random.default_rng(42)
    discharge = rng.lognormal(mean=8, sigma=0.5, size=len(dates))
    return pd.DataFrame({"discharge": discharge}, index=dates)


class TestWaterYearStats:
    def test_compute_returns_correct_shape(self):
        from app.services.water_year_service import compute_water_year_stats
        df = _make_discharge_df(5)
        stats = compute_water_year_stats("99999999", df, current_water_year=2024)
        assert isinstance(stats, list)
        assert len(stats) >= 365

    def test_compute_has_required_keys(self):
        from app.services.water_year_service import compute_water_year_stats
        df = _make_discharge_df(5)
        stats = compute_water_year_stats("99999999", df, current_water_year=2024)
        row = stats[0]
        for key in ("day_of_wy", "q10", "q25", "q50", "q75", "q90", "mean"):
            assert key in row, f"Missing key: {key}"

    def test_compute_excludes_current_water_year(self):
        from app.services.water_year_service import compute_water_year_stats
        df = _make_discharge_df(5)
        # Add data for current WY that is much higher
        future_dates = pd.date_range("2023-10-01", "2024-03-01", freq="D")
        future_df = pd.DataFrame({"discharge": np.full(len(future_dates), 999999.0)}, index=future_dates)
        combined = pd.concat([df, future_df])
        stats = compute_water_year_stats("99999999", combined, current_water_year=2024)
        # If current WY was included, q90 would be dominated by 999999 values
        assert stats[0]["q90"] < 100000

    def test_insufficient_data_returns_empty(self):
        from app.services.water_year_service import compute_water_year_stats
        tiny_df = pd.DataFrame({"discharge": [100.0] * 10}, index=pd.date_range("2020-01-01", periods=10))
        stats = compute_water_year_stats("99999999", tiny_df, current_water_year=2024)
        assert stats == []

    def test_percentile_ordering(self):
        from app.services.water_year_service import compute_water_year_stats
        df = _make_discharge_df(5)
        stats = compute_water_year_stats("99999999", df, current_water_year=2024)
        for row in stats:
            assert row["q10"] <= row["q25"] <= row["q50"] <= row["q75"] <= row["q90"]


class TestWaterYearEndpoint:
    def test_endpoint_returns_200(self, client):
        mock_stats = [{"day_of_wy": i, "q10": 100.0, "q25": 150.0, "q50": 200.0, "q75": 250.0, "q90": 300.0, "mean": 210.0} for i in range(1, 367)]
        with patch("app.routers.stations.get_water_year_stats") as mock_fn:
            mock_fn.return_value = mock_stats
            resp = client.get("/stations/14211720/water-year-stats")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 366

    def test_endpoint_returns_404_when_no_history(self, client):
        # Empty result = definitive "insufficient historical data".
        with patch("app.routers.stations.get_water_year_stats") as mock_fn:
            mock_fn.return_value = []
            resp = client.get("/stations/XXXXXXXX/water-year-stats")
        assert resp.status_code == 404

    def test_endpoint_returns_503_on_transient(self, client):
        from app.services.water_year_service import WaterYearDataUnavailable
        with patch("app.routers.stations.get_water_year_stats") as mock_fn:
            mock_fn.side_effect = WaterYearDataUnavailable("reset")
            resp = client.get("/stations/14211720/water-year-stats")
        assert resp.status_code == 503


class TestCurrentWaterYearEndpoint:
    def test_returns_200_with_series(self, client):
        series = [{"day_of_wy": 1, "discharge": 100.0}, {"day_of_wy": 2, "discharge": 110.0}]
        with patch("app.routers.stations.get_current_water_year_series") as mock_fn:
            mock_fn.return_value = series
            resp = client.get("/stations/14211720/current-water-year")
        assert resp.status_code == 200
        assert resp.json() == series

    def test_empty_series_is_200(self, client):
        with patch("app.routers.stations.get_current_water_year_series") as mock_fn:
            mock_fn.return_value = []
            resp = client.get("/stations/14211720/current-water-year")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_transient_is_503(self, client):
        from app.services.water_year_service import WaterYearDataUnavailable
        with patch("app.routers.stations.get_current_water_year_series") as mock_fn:
            mock_fn.side_effect = WaterYearDataUnavailable("reset")
            resp = client.get("/stations/14211720/current-water-year")
        assert resp.status_code == 503

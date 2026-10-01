"""Tests for weather data handling."""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock

from solar_challenge.weather import (
    validate_irradiance_data,
    WeatherCache,
    get_weather_cache,
    set_weather_cache,
    get_tmy_data,
)
from solar_challenge.location import Location


@pytest.fixture
def sample_index():
    """Create sample datetime index."""
    return pd.date_range("2024-01-01", periods=24, freq="h")


@pytest.fixture
def valid_weather_data(sample_index):
    """Create valid weather data DataFrame."""
    return pd.DataFrame({
        "ghi": np.linspace(0, 800, 24),
        "dni": np.linspace(0, 600, 24),
        "dhi": np.linspace(0, 300, 24),
        "temp_air": np.linspace(5, 15, 24),
        "wind_speed": np.full(24, 3.0),
    }, index=sample_index)


class TestValidateIrradianceData:
    """Test irradiance data validation."""

    def test_valid_data_passes(self, valid_weather_data):
        """Valid data passes validation without error."""
        validate_irradiance_data(valid_weather_data)  # Should not raise

    def test_missing_ghi_raises(self, sample_index):
        """Missing GHI column raises error."""
        data = pd.DataFrame({
            "dni": [100, 200],
            "dhi": [50, 100],
        }, index=sample_index[:2])
        with pytest.raises(ValueError, match="ghi"):
            validate_irradiance_data(data)

    def test_missing_dni_raises(self, sample_index):
        """Missing DNI column raises error."""
        data = pd.DataFrame({
            "ghi": [100, 200],
            "dhi": [50, 100],
        }, index=sample_index[:2])
        with pytest.raises(ValueError, match="dni"):
            validate_irradiance_data(data)

    def test_missing_dhi_raises(self, sample_index):
        """Missing DHI column raises error."""
        data = pd.DataFrame({
            "ghi": [100, 200],
            "dni": [50, 100],
        }, index=sample_index[:2])
        with pytest.raises(ValueError, match="dhi"):
            validate_irradiance_data(data)

    def test_negative_ghi_raises(self, sample_index):
        """Negative GHI values raise error."""
        data = pd.DataFrame({
            "ghi": [-10, 100],
            "dni": [50, 100],
            "dhi": [50, 50],
        }, index=sample_index[:2])
        with pytest.raises(ValueError, match="negative"):
            validate_irradiance_data(data)

    def test_ghi_exceeds_sum_raises(self, sample_index):
        """GHI > DNI + DHI raises error (physically impossible)."""
        data = pd.DataFrame({
            "ghi": [200, 100],
            "dni": [50, 50],
            "dhi": [50, 50],  # GHI=200 > DNI+DHI=100
        }, index=sample_index[:2])
        with pytest.raises(ValueError, match="exceeds"):
            validate_irradiance_data(data)


class TestWeatherCache:
    """Test weather data caching (LOC-004)."""

    @pytest.fixture
    def temp_cache_dir(self, tmp_path):
        """Create temporary cache directory."""
        cache_dir = tmp_path / "weather_cache"
        cache_dir.mkdir()
        return cache_dir

    @pytest.fixture
    def cache(self, temp_cache_dir):
        """Create cache with temporary directory."""
        return WeatherCache(cache_dir=temp_cache_dir)

    @pytest.fixture
    def bristol(self):
        """Bristol location fixture."""
        return Location.bristol()

    @pytest.fixture
    def sample_weather_data(self, sample_index):
        """Sample weather data for caching."""
        return pd.DataFrame({
            "ghi": np.linspace(0, 800, 24),
            "dni": np.linspace(0, 600, 24),
            "dhi": np.linspace(0, 300, 24),
            "temp_air": np.linspace(5, 15, 24),
        }, index=sample_index)

    def test_cache_directory_created(self, temp_cache_dir):
        """Cache directory is created if it doesn't exist."""
        new_cache_dir = temp_cache_dir / "new_cache"
        cache = WeatherCache(cache_dir=new_cache_dir)
        assert new_cache_dir.exists()

    def test_put_and_get_tmy(self, cache, bristol, sample_weather_data):
        """Data can be stored and retrieved from cache."""
        cache.put(sample_weather_data, "tmy", bristol)
        result = cache.get("tmy", bristol)
        assert result is not None
        pd.testing.assert_frame_equal(result, sample_weather_data)

    def test_get_returns_none_for_missing(self, cache, bristol):
        """Get returns None when data not in cache."""
        result = cache.get("tmy", bristol)
        assert result is None

    def test_put_and_get_with_date_range(self, cache, bristol, sample_weather_data):
        """An entry keyed by a date range can be stored and retrieved."""
        start = pd.Timestamp("2023-01-01")
        end = pd.Timestamp("2023-12-31")
        cache.put(sample_weather_data, "dated", bristol, start, end)
        result = cache.get("dated", bristol, start, end)
        assert result is not None
        pd.testing.assert_frame_equal(result, sample_weather_data)

    def test_different_locations_different_cache(self, cache, sample_weather_data):
        """Different locations use different cache entries."""
        loc1 = Location(latitude=51.45, longitude=-2.58)
        loc2 = Location(latitude=52.0, longitude=-1.0)
        cache.put(sample_weather_data, "tmy", loc1)
        result = cache.get("tmy", loc2)
        assert result is None

    def test_clear_removes_all(self, cache, bristol, sample_weather_data):
        """Clear removes all cached data."""
        cache.put(sample_weather_data, "tmy", bristol)
        count = cache.clear()
        assert count >= 1
        result = cache.get("tmy", bristol)
        assert result is None

    def test_invalidate_specific_entry(self, cache, bristol, sample_weather_data):
        """Invalidate removes specific cache entry."""
        cache.put(sample_weather_data, "tmy", bristol)
        removed = cache.invalidate("tmy", bristol)
        assert removed is True
        result = cache.get("tmy", bristol)
        assert result is None

    def test_invalidate_returns_false_if_not_found(self, cache, bristol):
        """Invalidate returns False if entry doesn't exist."""
        removed = cache.invalidate("tmy", bristol)
        assert removed is False


class TestGetTmyDataWithCache:
    """Test TMY data retrieval with caching."""

    @pytest.fixture
    def temp_cache(self, tmp_path):
        """Set up temporary cache."""
        cache_dir = tmp_path / "weather_cache"
        cache = WeatherCache(cache_dir=cache_dir)
        set_weather_cache(cache)
        yield cache
        set_weather_cache(None)

    @pytest.fixture
    def mock_tmy_data(self, sample_index):
        """Mock TMY data from PVGIS."""
        return pd.DataFrame({
            "ghi": np.linspace(0, 800, 24),
            "dni": np.linspace(0, 600, 24),
            "dhi": np.linspace(0, 300, 24),
            "temp_air": np.linspace(5, 15, 24),
        }, index=sample_index)

    def test_uses_cache_when_available(self, temp_cache, mock_tmy_data):
        """Uses cached data when available."""
        location = Location.bristol()
        temp_cache.put(mock_tmy_data, "tmy", location)

        with patch("solar_challenge.weather.get_pvgis_tmy") as mock_api:
            result = get_tmy_data(location, use_cache=True)
            mock_api.assert_not_called()
            pd.testing.assert_frame_equal(result, mock_tmy_data)

    def test_skips_cache_when_disabled(self, temp_cache, mock_tmy_data):
        """Skips cache when use_cache=False."""
        location = Location.bristol()
        temp_cache.put(mock_tmy_data, "tmy", location)

        with patch("solar_challenge.weather.get_pvgis_tmy") as mock_api:
            mock_api.return_value = (mock_tmy_data, None, None, None)
            result = get_tmy_data(location, use_cache=False)
            mock_api.assert_called_once()

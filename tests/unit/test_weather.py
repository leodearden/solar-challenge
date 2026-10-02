"""Tests for weather data handling."""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch

from solar_challenge.weather import (
    WeatherCache,
    set_weather_cache,
    get_tmy_data,
    scale_tmy_to_annual_ghi,
)
from solar_challenge.location import Location
from tests._synthetic_weather import synthetic_june_weather


@pytest.fixture
def sample_index():
    """Create sample datetime index."""
    return pd.date_range("2024-01-01", periods=24, freq="h")


@pytest.fixture
def pvgis_tmy():
    """A TMY shaped like PVGIS's as pvlib returns it: one non-leap 1990 of hourly UTC rows, its irradiance varying day to day."""
    utc_1990 = pd.date_range("1990-01-01", periods=8760, freq="h", tz="UTC")
    return (
        synthetic_june_weather("1990-01-01", irradiance_scale_per_day=np.linspace(0.2, 1.0, 365))
        .set_axis(utc_1990)
        .assign(relative_humidity=80.0)
    )


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


class TestScaleTmyToAnnualGhi:
    """scale_tmy_to_annual_ghi rescales one TMY year's irradiance to a given annual GHI."""

    IRRADIANCE = ["ghi", "dni", "dhi"]

    @pytest.fixture
    def target(self, pvgis_tmy):
        """An annual GHI 10% above the TMY's own, in kWh/m²."""
        return 1.1 * pvgis_tmy["ghi"].sum() / 1000

    def test_annual_ghi_equals_the_target(self, pvgis_tmy, target):
        """The scaled year's GHI sums to the target."""
        result = scale_tmy_to_annual_ghi(pvgis_tmy, target)
        assert result["ghi"].sum() / 1000 == pytest.approx(target, rel=1e-9)

    def test_ghi_dni_and_dhi_share_one_factor(self, pvgis_tmy, target):
        """Every irradiance component is multiplied by the same factor, so GHI = DNI·cos z + DHI still holds."""
        factor = target / (pvgis_tmy["ghi"].sum() / 1000)
        result = scale_tmy_to_annual_ghi(pvgis_tmy, target)
        for column in self.IRRADIANCE:
            pd.testing.assert_series_equal(result[column], pvgis_tmy[column] * factor, rtol=1e-12)

    def test_other_columns_and_index_are_unchanged(self, pvgis_tmy, target):
        """Temperature, wind, humidity and the timestamps are kept as they are."""
        result = scale_tmy_to_annual_ghi(pvgis_tmy, target)
        pd.testing.assert_frame_equal(
            result.drop(columns=self.IRRADIANCE), pvgis_tmy.drop(columns=self.IRRADIANCE)
        )

    def test_input_is_not_mutated(self, pvgis_tmy, target):
        """The TMY passed in is left as it was."""
        before = pvgis_tmy.copy(deep=True)
        scale_tmy_to_annual_ghi(pvgis_tmy, target)
        pd.testing.assert_frame_equal(pvgis_tmy, before)

    @pytest.mark.parametrize(
        ("make_tmy", "annual_ghi_kwh_per_m2", "condition"),
        [
            pytest.param(lambda tmy: tmy, 0.0, "annual_ghi_kwh_per_m2", id="target not positive"),
            pytest.param(lambda tmy: tmy.assign(ghi=0.0), 1000.0, "ghi total", id="no ghi in the year"),
            pytest.param(lambda tmy: tmy.iloc[:24], 1000.0, "8760", id="not one TMY year"),
        ],
    )
    def test_refuses_what_it_cannot_scale(self, pvgis_tmy, make_tmy, annual_ghi_kwh_per_m2, condition):
        """A ValueError names the condition that failed."""
        with pytest.raises(ValueError, match=condition):
            scale_tmy_to_annual_ghi(make_tmy(pvgis_tmy), annual_ghi_kwh_per_m2)

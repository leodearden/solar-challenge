"""Integration tests for PVGIS API calls.

These tests make real API calls and may be slow or flaky.
"""

import pytest
import pandas as pd
import numpy as np
from pvlib.solarposition import get_solarposition

from solar_challenge.location import Location
from solar_challenge.weather import get_tmy_data


@pytest.mark.slow
@pytest.mark.integration
class TestPVGISTMY:
    """Test PVGIS TMY data retrieval."""

    def test_get_tmy_for_bristol(self):
        """Retrieve TMY data for Bristol default location."""
        location = Location.bristol()
        data = get_tmy_data(location)

        # Should return a DataFrame
        assert isinstance(data, pd.DataFrame)

        # Should have datetime index
        assert isinstance(data.index, pd.DatetimeIndex)

        # Should have required columns
        assert "ghi" in data.columns
        assert "dni" in data.columns
        assert "dhi" in data.columns
        assert "temp_air" in data.columns

        # Should have roughly a year of hourly data
        assert len(data) >= 8760  # At least 1 year of hours

    def test_tmy_irradiance_is_physically_consistent(self):
        """Irradiance is never negative, GHI never exceeds DNI + DHI, and the year's GHI closes with DNI·cos(zenith) + DHI.

        The closure rejects a dni column that is not beam-normal irradiance: a
        beam-horizontal one, which is what PVGIS seriescalc's components are, closes at about 0.83.
        """
        location = Location.bristol()
        data = get_tmy_data(location)

        irradiance = data[["ghi", "dni", "dhi"]]
        assert (irradiance >= 0).all().all(), irradiance.min().to_dict()

        excess = data["ghi"] - (data["dni"] + data["dhi"])
        assert excess.max() <= 1.0, f"GHI exceeds DNI + DHI by {excess.max():.1f} W/m² at {excess.idxmax()}"

        zenith = get_solarposition(data.index, location.latitude, location.longitude)["zenith"]
        cos_zenith = np.cos(np.radians(zenith)).clip(lower=0.0)
        closure = (data["dni"] * cos_zenith + data["dhi"]).sum() / data["ghi"].sum()
        assert closure == pytest.approx(1.0, abs=0.02)

    def test_tmy_data_has_realistic_values(self):
        """TMY data has physically realistic values."""
        location = Location.bristol()
        data = get_tmy_data(location)

        # GHI should never exceed ~1400 W/m² (solar constant * air mass factor)
        assert data["ghi"].max() <= 1400

        # Temperature in Bristol should be between -20 and 40°C
        assert data["temp_air"].min() >= -20
        assert data["temp_air"].max() <= 40

        # Night hours should have zero irradiance
        assert (data["ghi"] == 0).any()

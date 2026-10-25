"""Contract tests of PVGIS's TMY for Bristol, as PvgisTmy returns it.

Each test checks PVGIS's live response, fetched once for the module, and one also checks
that the TMY committed under tests/fixtures/weather_cache is still that response.
"""

import pytest
import pandas as pd
import numpy as np
from pvlib.solarposition import get_solarposition

from solar_challenge.location import Location
from solar_challenge.weather import PvgisTmy
from tests._committed_weather_cache import REWRITE_THE_COMMITTED_BRISTOL_TMY, committed_bristol_tmy


BRISTOL = Location.bristol()


@pytest.fixture(scope="module")
def bristol_tmy() -> pd.DataFrame:
    """Bristol's TMY, fetched live from PVGIS once for every test in this module.

    It is never read from or written to a weather cache, whose copy may be months old.
    """
    return PvgisTmy(None).get(BRISTOL)


@pytest.mark.slow
class TestPVGISTMY:
    """Test PVGIS TMY data retrieval."""

    def test_get_tmy_for_bristol(self, bristol_tmy):
        """Retrieve TMY data for Bristol default location."""
        # Should return a DataFrame
        assert isinstance(bristol_tmy, pd.DataFrame)

        # Should have datetime index
        assert isinstance(bristol_tmy.index, pd.DatetimeIndex)

        # Should have required columns
        assert "ghi" in bristol_tmy.columns
        assert "dni" in bristol_tmy.columns
        assert "dhi" in bristol_tmy.columns
        assert "temp_air" in bristol_tmy.columns

        # Should have roughly a year of hourly data
        assert len(bristol_tmy) >= 8760  # At least 1 year of hours

    def test_tmy_irradiance_is_physically_consistent(self, bristol_tmy):
        """TMY irradiance components are non-negative and mutually consistent."""
        irradiance = bristol_tmy[["ghi", "dni", "dhi"]]
        assert (irradiance >= 0).all().all(), irradiance.min().to_dict()

        excess = bristol_tmy["ghi"] - (bristol_tmy["dni"] + bristol_tmy["dhi"])
        assert excess.max() <= 1.0, f"GHI exceeds DNI + DHI by {excess.max():.1f} W/m² at {excess.idxmax()}"

        zenith = get_solarposition(bristol_tmy.index, BRISTOL.latitude, BRISTOL.longitude)["zenith"]
        cos_zenith = np.cos(np.radians(zenith)).clip(lower=0.0)
        closure = (bristol_tmy["dni"] * cos_zenith + bristol_tmy["dhi"]).sum() / bristol_tmy["ghi"].sum()
        assert closure == pytest.approx(1.0, abs=0.02)

    def test_tmy_data_has_realistic_values(self, bristol_tmy):
        """TMY data has physically realistic values."""
        # GHI should never exceed ~1400 W/m² (solar constant * air mass factor)
        assert bristol_tmy["ghi"].max() <= 1400

        # Temperature in Bristol should be between -20 and 40°C
        assert bristol_tmy["temp_air"].min() >= -20
        assert bristol_tmy["temp_air"].max() <= 40

        # Night hours should have zero irradiance
        assert (bristol_tmy["ghi"] == 0).any()

    def test_tmy_annual_ghi_matches_the_2005_2020_mean(self, bristol_tmy):
        """Bristol's TMY sums to PVGIS's 2005-2020 mean GHI; docs/tmy-irradiation-scaling.md has the figure."""
        assert bristol_tmy["ghi"].sum() / 1000 == pytest.approx(1069.5, rel=0.01)

    def test_the_committed_bristol_tmy_equals_the_live_one(self, bristol_tmy):
        """The TMY committed under tests/fixtures/weather_cache is PVGIS's live one, exactly, so the year the yield guard measures is the year PvgisTmy gives users."""
        committed = committed_bristol_tmy()
        try:
            pd.testing.assert_frame_equal(bristol_tmy, committed, check_exact=True)
        except AssertionError as difference:
            raise AssertionError(
                "the Bristol TMY committed under tests/fixtures/weather_cache is no longer PVGIS's live one, so the "
                f"yield guard measures a year PvgisTmy no longer gives users. {REWRITE_THE_COMMITTED_BRISTOL_TMY}, "
                "then run tests/integration/test_pv_performance_ratio.py, whose yield test names what moves with a "
                f"new year, and amend the entry's provenance in docs/pv-cell-temperature.md §3\n{difference}"
            ) from None

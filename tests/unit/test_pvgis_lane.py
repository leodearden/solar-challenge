# SPDX-License-Identifier: AGPL-3.0-or-later
"""PVGIS lane contract tests.

tests/integration/test_pvgis.py checks PVGIS's TMY response as get_tmy_data
returns it, and holds only while each of its tests checks PVGIS itself, never
a cached copy.
"""

from pathlib import Path

import pandas as pd
import pvlib
import pytest

from solar_challenge.location import Location
from solar_challenge.weather import DEFAULT_CACHE_DIR, TMY_HOURS, WeatherCache

_PVGIS_CONTRACT_TESTS = "tests/integration/test_pvgis.py"
_DEAD_PROXY = "http://127.0.0.1:9"


def _clear_sky_tmy(location: Location) -> pd.DataFrame:
    """A TMY-shaped clear-sky year at *location*: TMY_HOURS hourly UTC rows with consistent ghi, dni and dhi."""
    hours = pd.date_range("1990-01-01", periods=TMY_HOURS, freq="h", tz="UTC")
    clear_sky = pvlib.location.Location(location.latitude, location.longitude).get_clearsky(
        hours, linke_turbidity=3.0
    )
    return clear_sky.assign(temp_air=10.0, wind_speed=2.0)


def test_no_pvgis_contract_test_passes_on_a_cached_tmy_while_pvgis_is_out_of_reach(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, project_root: Path
) -> None:
    """With PVGIS out of reach, no PVGIS contract test passes, though the working directory caches a clear-sky Bristol year.

    That year passes the module's shape and physics checks, so a test that read
    the cache instead of PVGIS would pass on it, checking a copy rather than
    PVGIS's current response.
    """
    bristol = Location.bristol()
    WeatherCache(cache_dir=pytester.path / DEFAULT_CACHE_DIR).put(_clear_sky_tmy(bristol), "tmy", bristol)
    # Every request then fails at the dead proxy, so no test can reach PVGIS.
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(name, _DEAD_PROXY)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)

    result = pytester.runpytest_subprocess(
        project_root / _PVGIS_CONTRACT_TESTS, "-p", "no:cacheprovider", timeout=120
    )

    outcomes = result.parseoutcomes()
    assert outcomes.get("passed", 0) == 0 and outcomes.get("failed", 0) + outcomes.get("errors", 0) > 0, (
        f"with PVGIS out of reach, the PVGIS contract tests ended {outcomes}: a test that passes checked "
        "the TMY cached in its working directory, not PVGIS's current response; fetch it with "
        "get_tmy_data(..., use_cache=False), as test_pvgis.py's bristol_tmy fixture does\n"
        f"stdout tail:\n{result.stdout.str()[-5000:]}"
    )

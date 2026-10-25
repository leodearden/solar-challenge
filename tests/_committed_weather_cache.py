# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bristol's TMY as the weather cache committed under tests/fixtures/weather_cache holds it, PVGIS's v5_3 TMY as PvgisTmy caches it, for tests that need a real Bristol year offline, together with the instruction for writing it again.

Usage::

    from tests._committed_weather_cache import REWRITE_THE_COMMITTED_BRISTOL_TMY, committed_bristol_tmy

    tmy = committed_bristol_tmy()
    failure = f"the committed Bristol TMY is no longer PVGIS's live one. {REWRITE_THE_COMMITTED_BRISTOL_TMY}"
"""

from pathlib import Path

import pandas as pd
import pytest

from solar_challenge.location import Location
from solar_challenge.weather import WeatherCache

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_WEATHER_CACHE_DIR = _REPOSITORY_ROOT / "tests" / "fixtures" / "weather_cache"
REWRITE_THE_COMMITTED_BRISTOL_TMY = (
    "With network access to PVGIS, from the repository root, write the entry again with "
    f'WeatherCache(cache_dir=Path("{COMMITTED_WEATHER_CACHE_DIR.relative_to(_REPOSITORY_ROOT).as_posix()}"))'
    '.put(PvgisTmy(None).get(Location.bristol()), "tmy", Location.bristol())'
)


def committed_bristol_tmy() -> pd.DataFrame:
    """Bristol's TMY as the committed weather cache holds it, read afresh on every call.

    Fails the calling test, naming the fix, when the cache's directory or its Bristol entry is missing. The
    directory is checked before any WeatherCache is built, because WeatherCache creates the directory it is given.
    """
    if not COMMITTED_WEATHER_CACHE_DIR.is_dir():
        pytest.fail(
            f"No directory is at {COMMITTED_WEATHER_CACHE_DIR}, where the weather cache holding Bristol's TMY "
            "is committed: restore it from git, or, if it moved, point tests/_committed_weather_cache.py's "
            "COMMITTED_WEATHER_CACHE_DIR at it"
        )
    tmy = WeatherCache(cache_dir=COMMITTED_WEATHER_CACHE_DIR).get("tmy", Location.bristol())
    if tmy is None:
        pytest.fail(
            f"WeatherCache reads no Bristol TMY entry in {COMMITTED_WEATHER_CACHE_DIR}, as after a change to "
            f"WeatherCache's keys. {REWRITE_THE_COMMITTED_BRISTOL_TMY}, delete the old entry's two files, "
            "and re-measure as docs/pv-cell-temperature.md §3 records"
        )
    return tmy

# SPDX-License-Identifier: AGPL-3.0-or-later
"""The default PV system's year on Bristol's PVGIS TMY performs at MCS's 0.8 and yields validation's Bristol constant.

scripts/measure_pv_performance_ratio.py measures the ratio that docs/pv-system-losses.md
defines and records; the note also sources the band. The same measurement's kWh per wired
kWp is validation.BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP to within 1%, the figure that
docs/pv-cell-temperature.md §3 records.
Why 1%: docs/prds/assistant-facts-from-engine.md §6 decision 3.

The TMY is the weather-cache entry committed under tests/fixtures/weather_cache: PVGIS's
v5_3 TMY for Bristol as PvgisTmy caches it, the entry docs/pv-cell-temperature.md §3's
measurement read. So these tests reach no network, and run in the per-task verify.
"""

from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
import pytest

from solar_challenge.location import Location
from solar_challenge.validation import BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP
from solar_challenge.weather import WeatherCache
from tests._scripts import load_script

COMMITTED_WEATHER_CACHE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "weather_cache"
MCS_PERFORMANCE_RATIO_LOW = 0.76
MCS_PERFORMANCE_RATIO_HIGH = 0.84
BRISTOL_YIELD_RELATIVE_TOLERANCE = 0.01


@pytest.fixture(scope="module")
def pv_performance_ratio() -> ModuleType:
    """scripts/measure_pv_performance_ratio.py."""
    return load_script("measure_pv_performance_ratio")


@pytest.fixture(scope="module")
def bristol_tmy() -> pd.DataFrame:
    """Bristol's TMY as the weather cache committed under tests/fixtures/weather_cache holds it: PVGIS's, as PvgisTmy caches it."""
    tmy = WeatherCache(cache_dir=COMMITTED_WEATHER_CACHE_DIR).get("tmy", Location.bristol())
    if tmy is None:
        pytest.fail(
            f"WeatherCache reads no Bristol TMY entry in {COMMITTED_WEATHER_CACHE_DIR}, as after a change to "
            "WeatherCache's keys. With network access to PVGIS, write the entry again with "
            f'PvgisTmy(WeatherCache(cache_dir=Path("{COMMITTED_WEATHER_CACHE_DIR}"))).get(Location.bristol()), '
            "delete the old entry's two files, and re-measure as docs/pv-cell-temperature.md §3 records"
        )
    return tmy


@pytest.fixture(scope="module")
def bristol_site(pv_performance_ratio: ModuleType, bristol_tmy: pd.DataFrame) -> Any:
    """measure_pv_performance_ratio's measurement of the default system over the committed Bristol TMY, one simulated year for every test here."""
    return pv_performance_ratio.measure("Bristol", Location.bristol(), bristol_tmy)


class TestBristolPerformanceRatio:
    """The ratio band is MCS's performance ratio of 0.8, +/- 5%; the yield is validation's Bristol constant, +/- 1%."""

    def test_the_default_system_performs_at_mcs_ratio(self, bristol_site: Any) -> None:
        lossless_ratio = bristol_site.lossless.performance_ratio
        ratio = bristol_site.with_losses.performance_ratio
        assert lossless_ratio > MCS_PERFORMANCE_RATIO_HIGH, (
            f"without system losses the default system's performance ratio is {lossless_ratio:.4f}, "
            f"not above MCS's {MCS_PERFORMANCE_RATIO_HIGH}, so the band no longer tests the losses"
        )
        assert MCS_PERFORMANCE_RATIO_LOW <= ratio <= MCS_PERFORMANCE_RATIO_HIGH, (
            f"the default system's annual performance ratio on Bristol's TMY is {ratio:.4f}, "
            f"outside MCS's {MCS_PERFORMANCE_RATIO_LOW}-{MCS_PERFORMANCE_RATIO_HIGH}"
        )

    def test_the_default_systems_yield_is_validations_bristol_constant(
        self, bristol_site: Any
    ) -> None:
        kwh_per_kwp = bristol_site.with_losses.kwh_per_kwp
        assert kwh_per_kwp == pytest.approx(
            BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP, rel=BRISTOL_YIELD_RELATIVE_TOLERANCE
        ), (
            f"the default system's yield on Bristol's TMY is {kwh_per_kwp:.2f} kWh per wired kWp, "
            f"more than {BRISTOL_YIELD_RELATIVE_TOLERANCE:.0%} from "
            f"validation.BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP, {BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP}: "
            "re-measure it with scripts/measure_pv_performance_ratio.py, record the figure in "
            "docs/pv-cell-temperature.md §3, and move the constant with it"
        )

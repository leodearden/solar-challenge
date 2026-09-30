# SPDX-License-Identifier: AGPL-3.0-or-later
"""TOU-optimized against greedy dispatch on Economy 7, with injected synthetic weather.

No PVGIS and not slow, so verify runs it. Non-slow counterpart of
tests/integration/test_tou_dispatch.py::TestTOUDispatchComparison::test_tou_dispatch_never_imports_more_at_peak_rate
Total cost is deliberately not asserted: TOU guarantees only what it imports at the peak rate.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import TariffConfig
from tests._synthetic_weather import synthetic_june_weather
from tests.integration._peak_rate_energy import off_peak_discharge_kwh, peak_rate_import_kwh

pytestmark = pytest.mark.integration

SUNNY_DAY = pd.Timestamp("2024-06-21")
SUNLESS_DAY = SUNNY_DAY + pd.Timedelta(days=1)


def _sunny_then_sunless_weather() -> pd.DataFrame:
    """Hourly weather where SUNNY_DAY has a clear day's sun and SUNLESS_DAY has none."""
    return synthetic_june_weather(SUNNY_DAY, irradiance_scale_per_day=(1.0, 0.0))


@pytest.fixture(scope="module")
def greedy_and_tou() -> tuple[SimulationResults, SimulationResults]:
    """The Economy 7 home of the slow file, simulated over both days with greedy, then TOU dispatch."""
    home = HomeConfig(
        pv_config=PVConfig.default_4kw(),
        load_config=LoadConfig(annual_consumption_kwh=3400.0, seed=42),
        battery_config=BatteryConfig.default_5kwh(),
        location=Location.bristol(),
        tariff_config=TariffConfig.economy_7(),
    )
    tou_home = dataclasses.replace(home, dispatch_strategy="tou_optimized")
    weather = _sunny_then_sunless_weather()
    return (
        simulate_home(home, SUNNY_DAY, SUNLESS_DAY, weather_data=weather),
        simulate_home(tou_home, SUNNY_DAY, SUNLESS_DAY, weather_data=weather),
    )


def test_tou_holds_the_battery_through_the_off_peak_window(
    greedy_and_tou: tuple[SimulationResults, SimulationResults],
) -> None:
    """Greedy spends the battery off-peak; TOU never discharges there.

    The greedy check shows the scenario tells the strategies apart. The TOU check
    is exact: its cheap-period branch never calls discharge.
    """
    greedy, tou = greedy_and_tou

    assert off_peak_discharge_kwh(greedy) > 0
    assert off_peak_discharge_kwh(tou) == 0.0


def test_tou_imports_less_at_the_peak_rate_than_greedy(
    greedy_and_tou: tuple[SimulationResults, SimulationResults],
) -> None:
    """TOU imports less than greedy at the peak rate.

    The general guarantee is "never more" (see the slow counterpart). The sunless
    day makes it strict here: greedy spent the battery overnight, while TOU spends
    that charge at the peak rate.
    """
    greedy, tou = greedy_and_tou

    assert peak_rate_import_kwh(tou) < peak_rate_import_kwh(greedy)

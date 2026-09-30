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

pytestmark = pytest.mark.integration

SUNNY_DAY = pd.Timestamp("2024-06-21")
SUNLESS_DAY = pd.Timestamp("2024-06-22")

# Hourly W/m² of a clear June day, copied from tests/unit/test_home.py::june21_weather_data.
CLEAR_JUNE_DAY_IRRADIANCE = {
    "ghi": [
        0, 0, 0, 0, 0, 50, 150, 300, 500, 650, 780, 850,
        870, 850, 780, 650, 500, 300, 150, 50, 0, 0, 0, 0,
    ],
    "dni": [
        0, 0, 0, 0, 0, 100, 250, 450, 650, 800, 900, 950,
        970, 950, 900, 800, 650, 450, 250, 100, 0, 0, 0, 0,
    ],
    "dhi": [
        0, 0, 0, 0, 0, 30, 70, 130, 180, 200, 200, 200,
        200, 200, 200, 200, 180, 130, 70, 30, 0, 0, 0, 0,
    ],
}


def _sunny_then_sunless_weather() -> pd.DataFrame:
    """Hourly weather for SUNNY_DAY, a clear June day, then SUNLESS_DAY, with no irradiance at all.

    Indexed in Europe/London, the timezone of the simulated demand.
    """
    index = pd.date_range(SUNNY_DAY, periods=48, freq="h", tz="Europe/London")
    irradiance = {
        column: [*clear_day, *[0.0] * len(clear_day)]
        for column, clear_day in CLEAR_JUNE_DAY_IRRADIANCE.items()
    }
    return pd.DataFrame(
        {**irradiance, "temp_air": 15.0, "wind_speed": 2.0},
        index=index,
    )


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


def _peak_rate_minutes(results: SimulationResults) -> pd.Series:
    """Mask of the minutes billed at the tariff's highest rate."""
    return results.tariff_rate == results.tariff_rate.max()


def test_tou_holds_the_battery_through_the_off_peak_window(
    greedy_and_tou: tuple[SimulationResults, SimulationResults],
) -> None:
    """Greedy spends the battery off-peak; TOU never discharges there.

    The greedy check shows the scenario tells the strategies apart. The TOU check
    is exact: its cheap-period branch never calls discharge.
    """
    greedy, tou = greedy_and_tou
    off_peak = ~_peak_rate_minutes(tou)

    assert greedy.battery_discharge[off_peak].sum() > 0
    assert tou.battery_discharge[off_peak].sum() == 0.0


def test_tou_imports_less_at_the_peak_rate_than_greedy(
    greedy_and_tou: tuple[SimulationResults, SimulationResults],
) -> None:
    """TOU imports less than greedy at the peak rate.

    The general guarantee is "never more" (see the slow counterpart). The sunless
    day makes it strict here: greedy spent the battery overnight, while TOU spends
    that charge at the peak rate (about 5.9 against 7.2 kWh imported).
    """
    greedy, tou = greedy_and_tou
    peak = _peak_rate_minutes(tou)

    assert tou.grid_import[peak].sum() < greedy.grid_import[peak].sum()

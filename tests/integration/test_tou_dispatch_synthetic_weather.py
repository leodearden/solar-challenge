# SPDX-License-Identifier: AGPL-3.0-or-later
"""TOU-optimized against greedy dispatch on Economy 7, with injected synthetic weather.

No PVGIS and not slow, so verify runs it. Total cost is deliberately not asserted: TOU
guarantees only what it imports at the peak rate, with or without a grid charge sized by a
forecast. The home has no seg_tariff, so simulate_home's warning that export revenue is 0.0
is ignored.
"""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import GridChargeConfig, TOUOptimizedStrategyConfig
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import TariffConfig
from tests._synthetic_weather import synthetic_june_weather, weather_for
from tests.integration._peak_rate_energy import off_peak_discharge_kwh, peak_rate_import_kwh

pytestmark = pytest.mark.filterwarnings("ignore:tariff_config is set but seg_tariff is None:UserWarning")

SUNNY_DAY = pd.Timestamp("2024-06-21")
SUNLESS_DAY = SUNNY_DAY + pd.Timedelta(days=1)
FIRST_OF_15_SUNNY_DAYS = SUNLESS_DAY - pd.Timedelta(days=15)
FLOAT_SUM_TOLERANCE_KWH = 1e-9
"""How far two peak-rate imports summed from per-minute floats may differ and still be equal."""


def _sunny_then_sunless_weather() -> pd.DataFrame:
    """Hourly weather where SUNNY_DAY has a clear day's sun and SUNLESS_DAY has none."""
    return synthetic_june_weather(SUNNY_DAY, irradiance_scale_per_day=(1.0, 0.0))


def _economy_7_home() -> HomeConfig:
    """An Economy 7 home with 4 kW of PV and a 5 kWh battery that does not grid-charge, dispatched greedily."""
    return HomeConfig(
        pv_config=PVConfig.default_4kw(),
        load_config=LoadConfig(annual_consumption_kwh=3400.0, seed=42),
        battery_config=BatteryConfig.default_5kwh(),
        location=Location.bristol(),
        tariff_config=TariffConfig.economy_7(),
    )


def _dispatched_tou_optimized(home: HomeConfig) -> HomeConfig:
    """home with its battery dispatched tou_optimized on its tariff's clock."""
    assert home.battery_config is not None
    return dataclasses.replace(
        home, battery_config=dataclasses.replace(home.battery_config, dispatch_strategy=TOUOptimizedStrategyConfig())
    )


@pytest.fixture(scope="module")
def greedy_and_tou() -> tuple[SimulationResults, SimulationResults]:
    """An Economy 7 home with a 5 kWh battery, simulated over both days with greedy, then TOU dispatch."""
    home = _economy_7_home()
    tou_home = _dispatched_tou_optimized(home)
    weather = _sunny_then_sunless_weather()
    return (
        simulate_home(home, SUNNY_DAY, SUNLESS_DAY, weather=weather_for(home, weather)),
        simulate_home(tou_home, SUNNY_DAY, SUNLESS_DAY, weather=weather_for(tou_home, weather)),
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

    The general guarantee is "never more". The sunless
    day makes it strict here: greedy spent the battery overnight, while TOU spends
    that charge at the peak rate.
    """
    greedy, tou = greedy_and_tou

    assert peak_rate_import_kwh(tou) < peak_rate_import_kwh(greedy)


@pytest.fixture(scope="module")
def runs_after_15_sunny_days() -> dict[str, SimulationResults]:
    """The Economy 7 home over 15 sunny days then SUNLESS_DAY: greedy, TOU, and TOU grid-charging to 90% sized by pv_blind and by trailing_14_days.

    The sunless day is the trailing forecast's worst case: 14 sunny days say PV will fill the
    battery after its cheap window, so the forecast under-charges it.
    """
    greedy = _economy_7_home()
    tou = _dispatched_tou_optimized(greedy)
    homes = {
        "greedy": greedy,
        "tou": tou,
        "tou+pv_blind": _grid_charging(tou, GridChargeConfig(0.9, forecast="pv_blind")),
        "tou+trailing_14_days": _grid_charging(tou, GridChargeConfig(0.9, forecast="trailing_14_days")),
    }
    weather = synthetic_june_weather(FIRST_OF_15_SUNNY_DAYS, irradiance_scale_per_day=(1.0,) * 15 + (0.0,))
    return {
        name: simulate_home(home, FIRST_OF_15_SUNNY_DAYS, SUNLESS_DAY, weather=weather_for(home, weather))
        for name, home in homes.items()
    }


def _grid_charging(home: HomeConfig, grid_charging: GridChargeConfig) -> HomeConfig:
    """home with its battery grid-charging as grid_charging says."""
    assert home.battery_config is not None
    return dataclasses.replace(home, battery_config=dataclasses.replace(home.battery_config, grid_charging=grid_charging))


def _peak_rate_imports(runs: dict[str, SimulationResults]) -> dict[str, float]:
    """Each run's peak-rate import in kWh, by its name."""
    return {name: peak_rate_import_kwh(results) for name, results in runs.items()}


def test_a_forecast_sized_fill_imports_between_the_pv_blind_fill_and_no_fill_at_the_peak_rate(
    runs_after_15_sunny_days: dict[str, SimulationResults],
) -> None:
    """pv_blind <= trailing_14_days <= no grid charge <= greedy at the peak rate.

    Each fill leaves the battery at least as full as a lower one at every minute after it, and
    TOU holds through every cheap minute that greedy spends, so no dispatch in the chain imports
    more at the peak rate than the one after it.
    """
    peak = _peak_rate_imports(runs_after_15_sunny_days)

    assert peak["tou+pv_blind"] <= peak["tou+trailing_14_days"] + FLOAT_SUM_TOLERANCE_KWH
    assert peak["tou+trailing_14_days"] <= peak["tou"] + FLOAT_SUM_TOLERANCE_KWH
    assert peak["tou"] <= peak["greedy"] + FLOAT_SUM_TOLERANCE_KWH


def test_the_sunless_day_after_15_sunny_ones_is_under_charged_by_trailing_14_days(
    runs_after_15_sunny_days: dict[str, SimulationResults],
) -> None:
    """The sunless day tells the forecast from the PV-blind fill, so the chain above is not equal by default."""
    peak = _peak_rate_imports(runs_after_15_sunny_days)

    assert peak["tou+pv_blind"] < peak["tou+trailing_14_days"]


def test_tou_holds_a_forecast_sized_battery_through_the_off_peak_window(
    runs_after_15_sunny_days: dict[str, SimulationResults],
) -> None:
    """A fill sized by trailing_14_days keeps TOU's cheap-window hold: it never discharges off-peak."""
    assert off_peak_discharge_kwh(runs_after_15_sunny_days["tou+trailing_14_days"]) == 0.0

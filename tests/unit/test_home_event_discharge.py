# SPDX-License-Identifier: AGPL-3.0-or-later
"""A home whose battery carries grid-services event windows discharges it at full power in them, and only in them.

docs/prds/event-dispatch-and-battery-sizing.md §5.2 defines the battery's event windows, §5.8
invariant 4 says a battery exports only in an event window, and §9 B4 is the behaviour pinned
here, at simulate_home's public seam, on the bristol-arbitrage home without grid charging.
"""

import dataclasses
from datetime import date
from typing import Optional

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import (
    DispatchStrategy,
    DispatchStrategyConfig,
    EventDischargeWindow,
    PeakShavingStrategyConfig,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategy,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from tests._exporting_runs import RUN_DAYS, home_of_the_runs
from tests._synthetic_weather import weather_for

_DAY_ID = "2024-01-15-sunless"
_EVENT = EventDischargeWindow(days=(date(2024, 1, 15),), hours=(17, 18))
"""An event on the run's day from 17:00 to 19:00."""
_EVENT_THE_RUN_DOES_NOT_REACH = EventDischargeWindow(days=(date(2024, 2, 1),), hours=(17,))
_EVENT_OPENS = pd.Timestamp("2024-01-15 17:00", tz="Europe/London")

_HOLDING_FOR_THE_PEAK = TOUOptimizedStrategyConfig(peak_hours=((16, 20),))
"""The base: it holds the battery's charge for a 16:00 to 20:00 peak, so it has charge to export from 17:00."""


def _home(
    strategy: DispatchStrategyConfig = _HOLDING_FOR_THE_PEAK, *windows: EventDischargeWindow
) -> HomeConfig:
    """home_of_the_runs(), its battery running *strategy* and carrying *windows*."""
    home = home_of_the_runs()
    battery = home.battery_config
    assert isinstance(battery, BatteryConfig)
    return dataclasses.replace(
        home, battery_config=dataclasses.replace(battery, dispatch_strategy=strategy, event_discharge=windows)
    )


def _run(home: HomeConfig, strategy: Optional[DispatchStrategy] = None) -> SimulationResults:
    """*home* over the sunless day, its balance checked every minute, under *strategy* or, without one, its battery's own."""
    weather, start, end = RUN_DAYS[_DAY_ID]
    return simulate_home(
        home,
        pd.Timestamp(start),
        pd.Timestamp(end),
        validate_balance=True,
        weather=weather_for(home, weather),
        strategy=strategy,
    )


def _on_the_runs_clock(index: pd.Index) -> pd.DatetimeIndex:
    assert isinstance(index, pd.DatetimeIndex)
    return index if index.tz is None else index.tz_convert("Europe/London")


def _in_the_event(index: pd.Index) -> "pd.Series[bool]":
    local = _on_the_runs_clock(index)
    inside = (local.date == date(2024, 1, 15)) & local.hour.isin([17, 18])
    return pd.Series(inside, index=index)


def _assert_exports_only_in_the_event(results: SimulationResults) -> None:
    export = results.battery_export
    assert export is not None
    assert (export > 0).any()
    assert (export[~_in_the_event(export.index)] == 0).all()


def test_an_enrolled_battery_exports_in_its_event_window_and_nowhere_else() -> None:
    _assert_exports_only_in_the_event(_run(_home(_HOLDING_FOR_THE_PEAK, _EVENT)))


def test_an_un_enrolled_battery_does_not_export() -> None:
    assert _run(_home()).battery_export is None


def test_an_enrolled_battery_holds_nothing_back_before_its_window_opens() -> None:
    enrolled = _run(_home(_HOLDING_FOR_THE_PEAK, _EVENT)).to_dataframe()
    un_enrolled = _run(_home()).to_dataframe()

    before = _on_the_runs_clock(un_enrolled.index) < _EVENT_OPENS

    pd.testing.assert_frame_equal(enrolled.loc[before, un_enrolled.columns], un_enrolled.loc[before])


def test_an_enrolled_run_is_named_for_its_wrapped_strategy() -> None:
    assert _run(_home(_HOLDING_FOR_THE_PEAK, _EVENT)).strategy_name == "event_discharge(tou_optimized)"


@pytest.mark.parametrize(
    "base",
    [
        pytest.param(SelfConsumptionStrategyConfig(), id="self_consumption"),
        pytest.param(_HOLDING_FOR_THE_PEAK, id="tou_optimized"),
        pytest.param(PeakShavingStrategyConfig(import_limit_kw=0.25), id="peak_shaving"),
    ],
)
def test_a_window_the_run_does_not_reach_leaves_every_base_running_as_before(base: DispatchStrategyConfig) -> None:
    enrolled = _run(_home(base, _EVENT_THE_RUN_DOES_NOT_REACH))

    assert enrolled.battery_export is None
    pd.testing.assert_frame_equal(enrolled.to_dataframe(), _run(_home(base)).to_dataframe())


def test_a_strategy_override_is_wrapped_in_the_batterys_windows() -> None:
    results = _run(_home(_HOLDING_FOR_THE_PEAK, _EVENT), TOUOptimizedStrategy([(16, 20)]))

    _assert_exports_only_in_the_event(results)
    assert results.strategy_name == "event_discharge(tou_optimized)"

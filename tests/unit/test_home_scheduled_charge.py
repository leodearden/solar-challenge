# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a home run under ScheduledChargeStrategy: a window over Economy 7's cheap period reproduces the home's own tou_optimized run.

scenarios/bristol-arbitrage.yaml's home runs tou_optimized on Economy 7's clock, grid-charging to
0.9 through the cheap period from 00:30 to 07:30. A daily window from 00:30 for 7 hours to 0.9 that
holds charges as that run does, and outside it either base dispatches as that run does at the dear
rate: SelfConsumptionStrategy, or TOUOptimizedStrategy with every hour peak but the window's.
"""

from datetime import time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from solar_challenge.dispatch import (
    ChargeWindow,
    DispatchStrategy,
    ScheduledChargeStrategy,
    SelfConsumptionStrategy,
    TOUOptimizedStrategy,
)
from solar_challenge.home import calculate_summary, simulate_home
from tests._bristol_arbitrage_home import bristol_arbitrage_home
from tests._synthetic_weather import sunless_weather, synthetic_june_weather, weather_for

_CHEAP_PERIOD_WINDOW = ChargeWindow("daily", time(0, 30), timedelta(hours=7), 0.9, False)
"""Economy 7's cheap period, 00:30 to 07:30, charging to the scenario's 0.9 grid-charging target."""


@pytest.mark.parametrize(
    "base",
    [
        pytest.param(SelfConsumptionStrategy(), id="over-self_consumption"),
        pytest.param(TOUOptimizedStrategy([(0, 1), (7, 24)]), id="over-tou_optimized"),
    ],
)
@pytest.mark.parametrize(
    ("day", "weather"),
    [
        pytest.param("2024-06-21", synthetic_june_weather("2024-06-21"), id="a-clear-june-day"),
        pytest.param("2024-01-15", sunless_weather("2024-01-15", temp_air=5.0), id="a-sunless-january-day"),
    ],
)
def test_a_window_over_the_cheap_period_reproduces_the_homes_own_tou_optimized_run(
    base: DispatchStrategy, day: str, weather: pd.DataFrame
) -> None:
    """Both take the PV charge first, size the grid charge from the SOC it leaves within the same headroom, and settle through one _settle_timestep, so only rounding parts them."""
    home = bristol_arbitrage_home()
    run_day = pd.Timestamp(day)
    strategy = ScheduledChargeStrategy(base, (_CHEAP_PERIOD_WINDOW,), ZoneInfo(home.location.timezone))

    windowed = simulate_home(home, run_day, run_day, weather=weather_for(home, weather), strategy=strategy)
    own = simulate_home(home, run_day, run_day, weather=weather_for(home, weather))

    assert calculate_summary(windowed).total_grid_charge_kwh > 0.0
    pd.testing.assert_frame_equal(
        windowed.to_dataframe(), own.to_dataframe(), check_exact=False, rtol=0, atol=1e-9
    )

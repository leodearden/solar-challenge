# SPDX-License-Identifier: AGPL-3.0-or-later
"""The synthetic one-minute June day of docs/prds/one-dispatch-engine.md §2.2, run into a battery through either engine.

The day is the 1,440 minutes of 2024-06-21, with PV of 3·sin(π(h − 5)/16) kW from 05:00 to 21:00 and none outside, h
being the hour of the day a minute starts at. A test gives the day its own demand and tariff, and runs it through
simulate_timestep, dispatched by a strategy, or through simulate_timestep_tou.

Usage::

    from tests._june_minute_day import MINUTES, inline_day, strategy_day

    def evening_peak_kw(h: float) -> float:
        return 0.4 + (1.5 if 17 <= h < 20 else 0.0)

    flows = strategy_day(battery, evening_peak_kw, TOUOptimizedStrategy([(16, 20)]), TariffConfig.economy_7())
    assert len(flows) == len(MINUTES)
"""

import math
from collections.abc import Callable

import pandas as pd

from solar_challenge.battery import Battery
from solar_challenge.dispatch import DispatchStrategy
from solar_challenge.flow import EnergyFlowResult, simulate_timestep, simulate_timestep_tou
from solar_challenge.tariff import TariffConfig

MINUTES = pd.date_range("2024-06-21 00:00", periods=1440, freq="min")

DemandProfile = Callable[[float], float]
"""A day's demand: the kW at an hour of the day, the hour as a fraction (07:30 is 7.5)."""


def strategy_day(
    battery: Battery, demand_kw: DemandProfile, strategy: DispatchStrategy, tariff: TariffConfig
) -> list[EnergyFlowResult]:
    """Each minute of the day's flows through simulate_timestep, dispatched by strategy on tariff."""
    return [
        simulate_timestep(
            _pv_kw(minute), demand_kw(_hour(minute)), battery, 1.0, minute.to_pydatetime(), strategy, tariff=tariff
        )
        for minute in MINUTES
    ]


def inline_day(battery: Battery, demand_kw: DemandProfile, tariff: TariffConfig) -> list[EnergyFlowResult]:
    """Each minute of the day's flows through simulate_timestep_tou on tariff."""
    return [
        simulate_timestep_tou(_pv_kw(minute), demand_kw(_hour(minute)), battery, minute, tariff, 1.0)
        for minute in MINUTES
    ]


def _hour(minute: pd.Timestamp) -> float:
    """The hour of the day minute starts at, as a fraction."""
    return float(minute.hour + minute.minute / 60)


def _pv_kw(minute: pd.Timestamp) -> float:
    """The day's PV: 3·sin(π(h − 5)/16) kW from 05:00 to 21:00, and none outside."""
    h = _hour(minute)
    return 3 * math.sin(math.pi * (h - 5) / 16) if 5 <= h < 21 else 0.0

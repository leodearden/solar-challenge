# SPDX-License-Identifier: AGPL-3.0-or-later
"""The synthetic one-minute June day of docs/prds/one-dispatch-engine.md §2.2, run into a battery through either engine.

The day is the 1,440 minutes of 2024-06-21, with PV of 3·sin(π(h − 5)/16) kW from 05:00 to 21:00 and none outside, h
being the hour of the day a minute starts at. A test gives the day its own demand and tariff, and runs it through
simulate_timestep, dispatched by a strategy, or through simulate_timestep_tou.

§2.2's morning-drain day is one such demand and battery: morning_drain_demand_kw, whose 3.5 kW drain from 06:00 to
13:00 empties the battery in Economy 10's expensive morning, and morning_drain_battery, a 10 kWh battery that
grid-charges to 0.6 of it.

Usage::

    from tests._june_minute_day import (
        MINUTES,
        inline_day,
        morning_drain_battery,
        morning_drain_demand_kw,
        strategy_day,
    )

    def evening_peak_kw(h: float) -> float:
        return 0.4 + (1.5 if 17 <= h < 20 else 0.0)

    flows = strategy_day(battery, evening_peak_kw, TOUOptimizedStrategy([(16, 20)]), TariffConfig.economy_7())
    assert len(flows) == len(MINUTES)

    inline = inline_day(morning_drain_battery(1.0), morning_drain_demand_kw, TariffConfig.economy_10())
"""

import math
from collections.abc import Callable

import pandas as pd

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import DispatchStrategy, GridChargeConfig
from solar_challenge.flow import EnergyFlowResult, simulate_timestep, simulate_timestep_tou
from solar_challenge.tariff import TariffConfig

MINUTES = pd.date_range("2024-06-21 00:00", periods=1440, freq="min")

DemandProfile = Callable[[float], float]
"""A day's demand: the kW at an hour of the day, the hour as a fraction (07:30 is 7.5)."""


def morning_drain_demand_kw(h: float) -> float:
    """The morning-drain day's demand: 0.4 kW, plus the 3.5 kW morning drain from 06:00 to 13:00 and 1.5 kW from 17:00 to 20:00."""
    return 0.4 + (3.5 if 6 <= h < 13 else 0.0) + (1.5 if 17 <= h < 20 else 0.0)


def morning_drain_battery(soc_kwh: float) -> Battery:
    """The morning-drain day's battery at soc_kwh: 10 kWh with the default 2.5 kW limits and 0.975 efficiencies, grid-charging to 0.6 of it, so its grid_charge_target_kwh is 6.0."""
    return Battery(BatteryConfig(capacity_kwh=10.0, grid_charging=GridChargeConfig(0.6)), initial_soc_kwh=soc_kwh)


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

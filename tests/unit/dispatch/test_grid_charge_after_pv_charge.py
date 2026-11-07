# SPDX-License-Identifier: AGPL-3.0-or-later
"""docs/prds/one-dispatch-engine.md §9 row 7: a cheap minute's grid charge is sized from the SOC after the minute's PV charge.

The fixtures are the PRD's §2.2 probes: one Economy 10 minute at 14:00, and the morning-drain Economy 10 day of
2024-06-21, both into a 10 kWh battery with the default 2.5 kW limits and 0.975 efficiencies, grid-charging to 0.6 of it.
"""

import math
from datetime import datetime

import pandas as pd
import pytest

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import (
    DispatchStrategy,
    GridChargeConfig,
    PeakShavingStrategy,
    TOUOptimizedStrategy,
)
from solar_challenge.flow import EnergyFlowResult, simulate_timestep, simulate_timestep_tou
from solar_challenge.tariff import TariffConfig

_E10 = TariffConfig.economy_10()

_MINUTES = pd.date_range("2024-06-21 00:00", periods=1440, freq="min")


def _battery(soc_kwh: float) -> Battery:
    """The fixture's battery at soc_kwh; its grid_charge_target_kwh is 6.0."""
    return Battery(BatteryConfig(capacity_kwh=10.0, grid_charging=GridChargeConfig(0.6)), initial_soc_kwh=soc_kwh)


def _hour(minute: pd.Timestamp) -> float:
    """The hour of the day minute starts at, as a fraction."""
    return minute.hour + minute.minute / 60


def _pv_kw(minute: pd.Timestamp) -> float:
    """The day's PV: 3·sin(π(h − 5)/16) kW from 05:00 to 21:00, and none outside."""
    h = _hour(minute)
    return 3 * math.sin(math.pi * (h - 5) / 16) if 5 <= h <= 21 else 0.0


def _demand_kw(minute: pd.Timestamp) -> float:
    """The day's demand: 0.4 kW, plus the 3.5 kW morning drain from 06:00 to 13:00 and 1.5 kW from 17:00 to 20:00."""
    h = _hour(minute)
    return 0.4 + (3.5 if 6 <= h < 13 else 0.0) + (1.5 if 17 <= h < 20 else 0.0)


_STRATEGIES = [
    pytest.param(TOUOptimizedStrategy([(5, 13), (16, 20), (22, 24)]), id="tou_optimized"),
    pytest.param(PeakShavingStrategy(2.0), id="peak_shaving"),
]
"""Both strategies that grid-charge in a cheap minute; the TOU peak hours are Economy 10's expensive hours. Both are stateless, so one instance serves every run."""


def _strategy_day(battery: Battery, strategy: DispatchStrategy) -> list[EnergyFlowResult]:
    """Each minute of the day's flows through simulate_timestep, dispatched by strategy on Economy 10."""
    return [
        simulate_timestep(_pv_kw(minute), _demand_kw(minute), battery, 1.0, minute.to_pydatetime(), strategy, tariff=_E10)
        for minute in _MINUTES
    ]


def _inline_day(battery: Battery) -> list[EnergyFlowResult]:
    """Each minute of the day's flows through simulate_timestep_tou on Economy 10."""
    return [simulate_timestep_tou(_pv_kw(minute), _demand_kw(minute), battery, minute, _E10, 1.0) for minute in _MINUTES]


class TestACheapMinuteWhosePvChargeReachesTheTarget:
    """At 14:00 on Economy 10, 1.5 kW of PV excess takes the battery from 5.98 kWh past its 6.0 kWh target on its own."""

    @pytest.mark.parametrize("strategy", _STRATEGIES)
    def test_it_stores_no_grid_energy(self, strategy: DispatchStrategy) -> None:
        result = simulate_timestep(2.0, 0.5, _battery(5.98), 1.0, datetime(2024, 6, 21, 14, 0), strategy, tariff=_E10)

        assert result.grid_charge == 0.0


class TestTheMorningDrainDay:
    """The day from 1.0 kWh: the cheap night grid-charges the battery to its target, the expensive morning's drain discharges it, and in the cheap afternoon PV recharges it while the grid tops up what that PV charge leaves short of the target."""

    def test_the_strategy_route_grid_charges_what_simulate_timestep_tou_does(self) -> None:
        inline = [result.grid_charge for result in _inline_day(_battery(1.0))]
        strategy = TOUOptimizedStrategy([(5, 13), (16, 20), (22, 24)])
        routed = [result.grid_charge for result in _strategy_day(_battery(1.0), strategy)]

        assert sum(inline) == pytest.approx(5.045223, abs=1e-6)
        assert routed == pytest.approx(inline, abs=1e-9)
        assert sum(routed) == pytest.approx(sum(inline), abs=1e-9)

    @pytest.mark.parametrize("strategy", _STRATEGIES)
    def test_no_step_that_grid_charges_ends_above_the_target(self, strategy: DispatchStrategy) -> None:
        battery = _battery(1.0)
        target_kwh = battery.grid_charge_target_kwh

        flows = _strategy_day(battery, strategy)

        assert [
            (minute, result.battery_soc)
            for minute, result in zip(_MINUTES, flows)
            if result.grid_charge > 0 and result.battery_soc > target_kwh + 1e-9
        ] == []

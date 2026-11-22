# SPDX-License-Identifier: AGPL-3.0-or-later
"""docs/prds/one-dispatch-engine.md §9 row 7: a cheap minute's grid charge is sized from the SOC after the minute's PV charge.

The fixtures are the PRD's §2.2 probes: one Economy 10 minute at 14:00, and the morning-drain Economy 10 day of
2024-06-21, both into a 10 kWh battery with the default 2.5 kW limits and 0.975 efficiencies, grid-charging to 0.6 of it.
"""

from datetime import datetime

import pytest

from solar_challenge.dispatch import (
    DispatchStrategy,
    PeakShavingStrategy,
    TOUOptimizedStrategy,
)
from solar_challenge.flow import simulate_timestep
from solar_challenge.tariff import TariffConfig
from tests._june_minute_day import (
    MINUTES,
    morning_drain_battery,
    morning_drain_demand_kw,
    strategy_day,
)
from tests._tou_on_the_tariff_s_clock import on_the_tariff_s_clock

_E10 = TariffConfig.economy_10()


_TOU = TOUOptimizedStrategy([(5, 13), (16, 20), (22, 24)])
"""TOU dispatch whose peak hours are Economy 10's expensive hours, the minutes in which TOUOptimizedStrategy on Economy 10's clock discharges the battery."""

_STRATEGIES = [
    pytest.param(_TOU, id="tou_optimized"),
    pytest.param(PeakShavingStrategy(1.0), id="peak_shaving"),
]
"""Both strategies that grid-charge in a cheap minute. Both are stateless, so one instance serves every run.

Peak shaving's 1.0 kW import limit has the morning drain discharge the battery to its floor, as _TOU does, so under both the
cheap afternoon has minutes in which the grid charges the battery alongside PV.
"""


class TestACheapMinuteWhosePvChargeReachesTheTarget:
    """At 14:00 on Economy 10, 1.5 kW of PV excess takes the battery from 5.98 kWh past its 6.0 kWh target on its own."""

    @pytest.mark.parametrize("strategy", _STRATEGIES)
    def test_it_stores_no_grid_energy(self, strategy: DispatchStrategy) -> None:
        result = simulate_timestep(
            2.0, 0.5, morning_drain_battery(5.98), 1.0, datetime(2024, 6, 21, 14, 0), strategy, tariff=_E10
        )

        assert result.grid_charge == 0.0


class TestTheMorningDrainDay:
    """The day from 1.0 kWh: the cheap night grid-charges the battery to its target, the expensive morning's drain discharges it, and in the cheap afternoon PV recharges it while the grid tops up what that PV charge leaves short of the target."""

    def test_peak_hours_at_the_tariff_s_expensive_hours_grid_charge_what_its_clock_does(self) -> None:
        on_the_clock = [
            result.grid_charge
            for result in strategy_day(
                morning_drain_battery(1.0), morning_drain_demand_kw, **on_the_tariff_s_clock(_E10)
            )
        ]
        on_peak_hours = [
            result.grid_charge for result in strategy_day(morning_drain_battery(1.0), morning_drain_demand_kw, _TOU, _E10)
        ]

        # The grid energy the battery drew; the 0.975 of it the battery stored is the PRD's 5.045223 kWh.
        assert sum(on_the_clock) == pytest.approx(5.174588, abs=1e-6)
        assert on_peak_hours == pytest.approx(on_the_clock, abs=1e-9)
        assert sum(on_peak_hours) == pytest.approx(sum(on_the_clock), abs=1e-9)

    @pytest.mark.parametrize("strategy", _STRATEGIES)
    def test_no_step_that_grid_charges_ends_above_the_target(self, strategy: DispatchStrategy) -> None:
        battery = morning_drain_battery(1.0)
        target_kwh = battery.grid_charge_target_kwh

        flows = strategy_day(battery, morning_drain_demand_kw, strategy, _E10)

        assert [
            (minute, result.battery_soc)
            for minute, result in zip(MINUTES, flows)
            if result.grid_charge > 0 and result.battery_soc > target_kwh + 1e-9
        ] == []

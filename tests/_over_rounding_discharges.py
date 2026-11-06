# SPDX-License-Identifier: AGPL-3.0-or-later
"""Battery discharges whose withdrawal, less the discharge losses, rounds an ulp above the energy they ask for, and the battery they do so on.

Battery.discharge withdraws the energy it is asked for divided by its discharge_efficiency,
and that withdrawal times the efficiency is what reaches the home. At a discharge_efficiency
of 0.975, the round trip lands one ulp above the energy asked for at each (power in kW,
duration in minutes) of OVER_ROUNDING_DISCHARGES, found by probe at a 1, 5, 30 and 60-minute
step. At 0.95 or 0.99 none of them does, so BATTERY_THEY_OVER_ROUND_ON sets the efficiency
rather than taking the default. Its 2.5 kW limit and the charge a fresh Battery starts with
cover each discharge, so neither caps one.

Usage::

    from tests._over_rounding_discharges import BATTERY_THEY_OVER_ROUND_ON, OVER_ROUNDING_DISCHARGES

    @pytest.mark.parametrize(("power_kw", "duration_minutes"), OVER_ROUNDING_DISCHARGES)
    def test_a_discharge_delivers_no_more_than_it_asks_for(power_kw: float, duration_minutes: float) -> None:
        asked_kwh = power_kw * (duration_minutes * HOURS_PER_MINUTE)
        assert Battery(BATTERY_THEY_OVER_ROUND_ON).discharge(power_kw, duration_minutes) <= asked_kwh
"""

import dataclasses

import pytest

from solar_challenge.battery import BatteryConfig

#: A default 5 kWh battery at the discharge efficiency OVER_ROUNDING_DISCHARGES were found at.
BATTERY_THEY_OVER_ROUND_ON = dataclasses.replace(BatteryConfig.default_5kwh(), discharge_efficiency=0.975)

#: (power in kW, duration in minutes) of each discharge that over-rounds on BATTERY_THEY_OVER_ROUND_ON.
OVER_ROUNDING_DISCHARGES = (
    pytest.param(0.463, 1.0, id="0.463kW-1min"),
    pytest.param(0.737, 5.0, id="0.737kW-5min"),
    pytest.param(0.247, 30.0, id="0.247kW-30min"),
    pytest.param(0.494, 60.0, id="0.494kW-60min"),
)

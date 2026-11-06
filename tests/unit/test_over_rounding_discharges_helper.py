# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_over_rounding_discharges.py: each of its discharges over-rounds on its battery, as its tests rely on."""

import math

import pytest

from solar_challenge.timebase import HOURS_PER_MINUTE
from tests._over_rounding_discharges import BATTERY_THEY_OVER_ROUND_ON, OVER_ROUNDING_DISCHARGES


@pytest.mark.parametrize(("power_kw", "duration_minutes"), OVER_ROUNDING_DISCHARGES)
def test_each_discharge_withdraws_an_energy_that_less_the_losses_lands_one_ulp_above_the_energy_it_asks_for(
    power_kw: float, duration_minutes: float
) -> None:
    efficiency = BATTERY_THEY_OVER_ROUND_ON.discharge_efficiency
    asked_kwh = power_kw * (duration_minutes * HOURS_PER_MINUTE)
    assert (asked_kwh / efficiency) * efficiency == math.nextafter(asked_kwh, math.inf)

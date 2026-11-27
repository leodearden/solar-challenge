# SPDX-License-Identifier: AGPL-3.0-or-later
"""The 10 kWh battery the dispatch tests step, at the state of charge each test starts it at.

Its limits and efficiencies are BatteryConfig's defaults, 2.5 kW and 0.975, so the energies a test
expects, and the limits its refusals name, follow from those.

Usage::

    from tests._ten_kwh_battery import ten_kwh_battery

    result = simulate_timestep(0.0, 1.0, ten_kwh_battery(5.0), 60, strategy=strategy)
"""

from solar_challenge.battery import Battery, BatteryConfig


def ten_kwh_battery(soc_kwh: float) -> Battery:
    """A 10 kWh battery at *soc_kwh*, with the default 2.5 kW limits and 0.975 efficiencies."""
    return Battery(BatteryConfig(capacity_kwh=10.0), initial_soc_kwh=soc_kwh)

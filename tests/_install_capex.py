# SPDX-License-Identifier: AGPL-3.0-or-later
"""The finance tests' oracle for the capex project_economics prices: the PV DC a fleet's homes wire, and each home's roof, battery, inverter and battery inverter.

A projection's curve carries fleet_wired_dc_kw of its fleet's homes, on which project_economics prices the PV term,
and project_economics adds roof_battery_inverter_capex_gbp of those homes.

Usage::

    from tests._install_capex import fleet_wired_dc_kw, roof_battery_inverter_capex_gbp

    capex = fleet_wired_dc_kw(homes) * finance.pv_cost_per_kwp_gbp + roof_battery_inverter_capex_gbp(homes, finance)
"""

from collections.abc import Sequence

from solar_challenge.finance import FinanceConfig
from solar_challenge.home import HomeConfig
from solar_challenge.pv import wired_dc_capacity_kw


def fleet_wired_dc_kw(homes: Sequence[HomeConfig]) -> float:
    """Σ wired_dc_capacity_kw of *homes*' PV configs, in kWp."""
    return sum(wired_dc_capacity_kw(home.pv_config) for home in homes)


def roof_battery_inverter_capex_gbp(homes: Sequence[HomeConfig], finance: FinanceConfig) -> float:
    """Σ over *homes* of the roof fit, battery kWh × battery cost, effective inverter kW × inverter cost and battery max_discharge_kw × battery-inverter cost (no battery term without a battery), in £."""
    return sum(
        finance.roof_fit_cost_gbp
        + (0.0 if home.battery_config is None else home.battery_config.capacity_kwh) * finance.battery_cost_per_kwh_gbp
        + home.pv_config.effective_inverter_capacity_kw * finance.inverter_cost_per_kw_gbp
        + (0.0 if home.battery_config is None else home.battery_config.max_discharge_kw)
        * finance.battery_inverter_cost_per_kw_gbp
        for home in homes
    )

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write configs as the scenario YAML documents config.py's loaders read.

Each block written here is the inverse of the config.py parser that reads it:
parse_location_block, parse_home_block and its block parsers, parse_tariff_config's
custom type, and parse_seg_rate.  A block carries every key its parser reads, an
absent value written as null, which those parsers read as their default or None.
"""

from collections.abc import Mapping
from typing import Any, Optional

import yaml

from solar_challenge.battery import BatteryConfig
from solar_challenge.ev import EVConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig


def scenario_yaml(document: Mapping[str, Any]) -> str:
    """The YAML text of a scenario *document*, its keys in the order written."""
    text: str = yaml.safe_dump(
        dict(document), default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    return text


def location_block(location: Location) -> dict[str, Any]:
    """The location: block parse_location_block reads back as *location*."""
    return {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "timezone": location.timezone,
        "altitude": location.altitude,
        "name": location.name,
    }


def home_scenario(home: HomeConfig, *, name: str) -> dict[str, Any]:
    """The scenario *name* that `home run` reads back as *home*, its SEG tariff unnamed."""
    return {
        "name": name,
        "location": location_block(home.location),
        "home": _home_block(home),
        "seg": _seg_block(home.seg_tariff),
    }


def _home_block(home: HomeConfig) -> dict[str, Any]:
    """The home: block parse_home_block reads back as *home*, location and SEG aside."""
    return {
        "name": home.name,
        "pv": _pv_block(home.pv_config),
        "battery": None if home.battery_config is None else _battery_block(home.battery_config),
        "load": _load_block(home.load_config),
        "tariff": None if home.tariff_config is None else _tariff_block(home.tariff_config),
        "dispatch_strategy": home.dispatch_strategy,
        "heat_pump": (
            None if home.heat_pump_config is None else _heat_pump_block(home.heat_pump_config)
        ),
        "ev": None if home.ev_config is None else _ev_block(home.ev_config),
    }


def _pv_block(pv: PVConfig) -> dict[str, Any]:
    """The pv: block _parse_pv_config reads back as *pv*.

    Raises:
        ValueError: naming the custom pvlib parameters *pv* sets, which no pv: key carries.
    """
    inexpressible = [
        field
        for field, value in (
            ("custom_module_params", pv.custom_module_params),
            ("custom_inverter_params", pv.custom_inverter_params),
        )
        if value is not None
    ]
    if inexpressible:
        raise ValueError(
            f"PV {' and '.join(inexpressible)} cannot be written as scenario YAML: "
            "the pv: block has no key for custom pvlib parameters"
        )
    return {
        "capacity_kw": pv.capacity_kw,
        "azimuth": pv.azimuth,
        "tilt": pv.tilt,
        "name": pv.name,
        "module_efficiency": pv.module_efficiency,
        "temperature_coefficient": pv.temperature_coefficient,
        "inverter_efficiency": pv.inverter_efficiency,
        "inverter_capacity_kw": pv.inverter_capacity_kw,
        "system_age_years": pv.system_age_years,
        "degradation_rate_per_year": pv.degradation_rate_per_year,
    }


def _battery_block(battery: BatteryConfig) -> dict[str, Any]:
    """The battery: block _parse_battery_config reads back as *battery*.

    A round-trip efficiency is written without the per-direction efficiencies
    BatteryConfig derives from it.
    """
    efficiencies: dict[str, Any] = (
        {"efficiency": battery.efficiency}
        if battery.efficiency is not None
        else {
            "charge_efficiency": battery.charge_efficiency,
            "discharge_efficiency": battery.discharge_efficiency,
        }
    )
    return {
        "capacity_kwh": battery.capacity_kwh,
        "max_charge_kw": battery.max_charge_kw,
        "max_discharge_kw": battery.max_discharge_kw,
        "name": battery.name,
        "dispatch_strategy": _dispatch_strategy_block(battery),
        "grid_charging": (
            None
            if battery.grid_charging is None
            else {"target_soc_fraction": battery.grid_charging.target_soc_fraction}
        ),
        "min_soc_fraction": battery.min_soc_fraction,
        "max_soc_fraction": battery.max_soc_fraction,
        **efficiencies,
        "system_age_years": battery.system_age_years,
        "calendar_fade_rate_per_year": battery.calendar_fade_rate_per_year,
        "cycle_fade_per_equivalent_full_cycle": battery.cycle_fade_per_equivalent_full_cycle,
        "soh_floor": battery.soh_floor,
        "soh": battery.soh,
    }


def _dispatch_strategy_block(battery: BatteryConfig) -> Optional[dict[str, Any]]:
    """The dispatch_strategy: block parse_dispatch_strategy_config reads back as *battery*'s."""
    strategy = battery.dispatch_strategy
    if strategy is None:
        return None
    peak_hours = strategy.peak_hours
    return {
        "strategy_type": strategy.strategy_type,
        "peak_hours": None if peak_hours is None else [[start, end] for start, end in peak_hours],
        "import_limit_kw": strategy.import_limit_kw,
    }


def _load_block(load: LoadConfig) -> dict[str, Any]:
    """The load: block _parse_load_config reads back as *load*."""
    return {
        "annual_consumption_kwh": load.annual_consumption_kwh,
        "household_occupants": load.household_occupants,
        "name": load.name,
        "use_stochastic": load.use_stochastic,
        "seed": load.seed,
    }


def _tariff_block(tariff: TariffConfig) -> dict[str, Any]:
    """The tariff: block parse_tariff_config reads back as *tariff*: its periods, as a custom tariff."""
    return {
        "type": "custom",
        "name": tariff.name,
        "periods": [
            {
                "start_time": period.start_time,
                "end_time": period.end_time,
                "rate_per_kwh": period.rate_per_kwh,
                "name": period.name,
            }
            for period in tariff.periods
        ],
    }


def _heat_pump_block(heat_pump: HeatPumpConfig) -> dict[str, Any]:
    """The heat_pump: block _parse_heat_pump_config reads back as *heat_pump*."""
    return {
        "heat_pump_type": heat_pump.heat_pump_type,
        "thermal_capacity_kw": heat_pump.thermal_capacity_kw,
        "annual_heat_demand_kwh": heat_pump.annual_heat_demand_kwh,
        "name": heat_pump.name,
    }


def _ev_block(ev: EVConfig) -> dict[str, Any]:
    """The ev: block _parse_ev_config reads back as *ev*."""
    return {
        "charger_type": ev.charger_type,
        "arrival_hour": ev.arrival_hour,
        "departure_hour": ev.departure_hour,
        "required_charge_kwh": ev.required_charge_kwh,
        "smart_charging_mode": ev.smart_charging_mode,
        "name": ev.name,
    }


def _seg_block(seg_tariff: Optional[SEGTariff]) -> Optional[dict[str, Any]]:
    """The seg: block parse_seg_rate reads back as *seg_tariff*'s rate; it carries no tariff name."""
    if seg_tariff is None:
        return None
    return {"rate_pence_per_kwh": seg_tariff.rate_pence_per_kwh}

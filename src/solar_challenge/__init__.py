# SPDX-License-Identifier: AGPL-3.0-or-later
"""Solar Challenge Energy Flow Simulator.

A simulation toolkit for modelling domestic PV and battery systems
in the Bristol area, supporting both individual home and fleet-level analysis.
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Frozen public surface — PRD §3.1
# Adding a name is additive/back-compat; removing/renaming is a breaking change.
# CLI (get_cli_app) is deliberately excluded — shipped but unfrozen.
# ---------------------------------------------------------------------------
__all__: list[str] = [
    # --- finance / bill engine (finance.py; FinanceConfig relocated there, T2) ---
    "householder_bill",
    "solve_cost_recovery_rate",
    "bill_distribution",
    "BillBreakdown",
    "BillDistribution",
    "CostRecoverySolution",
    "FinanceConfig",
    # --- signature-closure types required to call the bill engine ---
    "SummaryStatistics",   # home.py   — arg to householder_bill
    "ScenarioConfig",      # config.py — arg to solve_cost_recovery_rate
    "FleetConfig",         # fleet.py  — in solve_cost_recovery_rate's simulate signature
    "FleetResults",        # fleet.py  — return type of simulate
    # --- dispatch (dispatch.py) ---
    "DispatchStrategy",
    "DispatchDecision",
    "GridChargeContext",
    "compute_grid_charge_power_kw",
    "SelfConsumptionStrategy",
    "TOUOptimizedStrategy",
    "PeakShavingStrategy",
    "DispatchTariffPeriod",     # alias for dispatch.TariffPeriod (collision-renamed)
    # --- battery (battery.py) ---
    "Battery",
    "BatteryConfig",
    "compute_soh",
    # --- flow (flow.py) ---
    "EnergyFlowResult",
    "simulate_timestep",
    "simulate_timestep_tou",
    "validate_energy_balance",
    "calculate_self_consumption",
    "calculate_excess_pv",
    "calculate_shortfall",
    # --- tariff (tariff.py) ---
    "TariffConfig",
    "TariffPeriod",
    "calculate_bill",
    "FlatRateTariff",
    # --- seg (seg.py) ---
    "SEGTariff",
    "resolve_seg_tariff",
    "calculate_seg_revenue",
    "SEG_PRESETS",
    # --- gridservices (gridservices.py) ---
    "GridServicesRateBand",
    "GridServicesRateBands",
    "resolve_grid_services_rate_band",
    "EventWindow",
    "GridServicesEventsConfig",
    "GridServicesAtEvents",
    "compute_fleet_spare_capacity_kw",
    "compute_grid_services_at_events",
    "GRID_SERVICES_RATE_BANDS",
    "DEFAULT_EVENT_WINDOWS",
    # --- community (community.py) ---
    "CommunityConfig",
    "CommunityBillingConfig",
    "CommunityResults",
    "simulate_community",
    "validate_community_balance",
    # --- pv (pv.py) ---
    "PVConfig",
    "simulate_pv_output",
    "create_model_chain",
    "create_pv_system",
    "apply_degradation",
    "calculate_degradation_factor",
    "interpolate_to_minute_resolution",
    # --- weather (weather.py) ---
    "get_tmy_data",
    "WeatherCache",
    "get_weather_cache",
    "set_weather_cache",
    # --- load (load.py) ---
    "LoadConfig",
    "OFGEM_TDCV_BY_OCCUPANTS",
    "ELEXON_PROFILE_CLASS_1",
    "SEASONAL_FACTORS",
    # --- location (location.py) — required by pv/weather call signatures ---
    "Location",
]

# ---------------------------------------------------------------------------
# Internal mapping: public name → origin submodule
# Invariant: set(_SYMBOL_MODULE.keys()) == set(__all__)
# ---------------------------------------------------------------------------
_SYMBOL_MODULE: dict[str, str] = {
    # finance
    "householder_bill": "finance",
    "solve_cost_recovery_rate": "finance",
    "bill_distribution": "finance",
    "BillBreakdown": "finance",
    "BillDistribution": "finance",
    "CostRecoverySolution": "finance",
    "FinanceConfig": "finance",
    # signature-closure types
    "SummaryStatistics": "home",
    "ScenarioConfig": "config",
    "FleetConfig": "fleet",
    "FleetResults": "fleet",
    # dispatch
    "DispatchStrategy": "dispatch",
    "DispatchDecision": "dispatch",
    "GridChargeContext": "dispatch",
    "compute_grid_charge_power_kw": "dispatch",
    "SelfConsumptionStrategy": "dispatch",
    "TOUOptimizedStrategy": "dispatch",
    "PeakShavingStrategy": "dispatch",
    "DispatchTariffPeriod": "dispatch",   # alias — source name is TariffPeriod
    # battery
    "Battery": "battery",
    "BatteryConfig": "battery",
    "compute_soh": "battery",
    # flow
    "EnergyFlowResult": "flow",
    "simulate_timestep": "flow",
    "simulate_timestep_tou": "flow",
    "validate_energy_balance": "flow",
    "calculate_self_consumption": "flow",
    "calculate_excess_pv": "flow",
    "calculate_shortfall": "flow",
    # tariff
    "TariffConfig": "tariff",
    "TariffPeriod": "tariff",
    "calculate_bill": "tariff",
    "FlatRateTariff": "tariff",
    # seg
    "SEGTariff": "seg",
    "resolve_seg_tariff": "seg",
    "calculate_seg_revenue": "seg",
    "SEG_PRESETS": "seg",
    # gridservices
    "GridServicesRateBand": "gridservices",
    "GridServicesRateBands": "gridservices",
    "resolve_grid_services_rate_band": "gridservices",
    "EventWindow": "gridservices",
    "GridServicesEventsConfig": "gridservices",
    "GridServicesAtEvents": "gridservices",
    "compute_fleet_spare_capacity_kw": "gridservices",
    "compute_grid_services_at_events": "gridservices",
    "GRID_SERVICES_RATE_BANDS": "gridservices",
    "DEFAULT_EVENT_WINDOWS": "gridservices",
    # community
    "CommunityConfig": "community",
    "CommunityBillingConfig": "community",
    "CommunityResults": "community",
    "simulate_community": "community",
    "validate_community_balance": "community",
    # pv
    "PVConfig": "pv",
    "simulate_pv_output": "pv",
    "create_model_chain": "pv",
    "create_pv_system": "pv",
    "apply_degradation": "pv",
    "calculate_degradation_factor": "pv",
    "interpolate_to_minute_resolution": "pv",
    # weather
    "get_tmy_data": "weather",
    "WeatherCache": "weather",
    "get_weather_cache": "weather",
    "set_weather_cache": "weather",
    # load
    "LoadConfig": "load",
    "OFGEM_TDCV_BY_OCCUPANTS": "load",
    "ELEXON_PROFILE_CLASS_1": "load",
    "SEASONAL_FACTORS": "load",
    # location
    "Location": "location",
}

# Sanity check at import time: every __all__ name must have a mapping.
# Uses an explicit RuntimeError (not bare assert) so the check survives -O/-OO.
if set(_SYMBOL_MODULE) != set(__all__):
    raise RuntimeError(
        f"_SYMBOL_MODULE / __all__ mismatch: "
        f"extra={set(_SYMBOL_MODULE)-set(__all__)}, "
        f"missing={set(__all__)-set(_SYMBOL_MODULE)}"
    )

# ---------------------------------------------------------------------------
# Alias resolution: public name differs from the symbol name in the origin module
# ---------------------------------------------------------------------------
_SOURCE_NAME: dict[str, str] = {
    "DispatchTariffPeriod": "TariffPeriod",   # dispatch.TariffPeriod (Enum) — collision-renamed
}

# ---------------------------------------------------------------------------
# PEP-562 lazy attribute loader
# ---------------------------------------------------------------------------
def __getattr__(name: str) -> Any:
    """PEP-562 hook: resolve public names lazily on first attribute access.

    Caches the resolved object into globals() so subsequent accesses are plain
    attribute hits (no repeated importlib calls).
    """
    mod_name = _SYMBOL_MODULE.get(name)
    if mod_name is None:
        raise AttributeError(f"module 'solar_challenge' has no attribute {name!r}")
    module = importlib.import_module(f"solar_challenge.{mod_name}")
    obj = getattr(module, _SOURCE_NAME.get(name, name))
    globals()[name] = obj   # cache for repeat access
    return obj


def __dir__() -> list[str]:
    """Return exactly the frozen public surface for `dir(solar_challenge)`."""
    return sorted(__all__)


# ---------------------------------------------------------------------------
# Lazy CLI accessor (get_cli_app is NOT in __all__ — shipped, unfrozen)
# ---------------------------------------------------------------------------
def get_cli_app() -> "Typer":
    """Get the Typer CLI app for programmatic access.

    Returns:
        typer.Typer: The main CLI application
    """
    from solar_challenge.cli import app
    return app


# ---------------------------------------------------------------------------
# TYPE_CHECKING block — carries the typed surface for consumer mypy --strict.
# Never executed at runtime; validated by `uv run --extra dev --extra web mypy src/solar_challenge`.
# Explicit `as` re-exports satisfy mypy strict --no-implicit-reexport.
# ---------------------------------------------------------------------------
if TYPE_CHECKING:
    from typer import Typer  # for get_cli_app() return annotation

    # finance
    from solar_challenge.finance import householder_bill as householder_bill
    from solar_challenge.finance import solve_cost_recovery_rate as solve_cost_recovery_rate
    from solar_challenge.finance import bill_distribution as bill_distribution
    from solar_challenge.finance import BillBreakdown as BillBreakdown
    from solar_challenge.finance import BillDistribution as BillDistribution
    from solar_challenge.finance import CostRecoverySolution as CostRecoverySolution
    from solar_challenge.finance import FinanceConfig as FinanceConfig
    # signature-closure types
    from solar_challenge.home import SummaryStatistics as SummaryStatistics
    from solar_challenge.config import ScenarioConfig as ScenarioConfig
    from solar_challenge.fleet import FleetConfig as FleetConfig
    from solar_challenge.fleet import FleetResults as FleetResults
    # dispatch
    from solar_challenge.dispatch import DispatchStrategy as DispatchStrategy
    from solar_challenge.dispatch import DispatchDecision as DispatchDecision
    from solar_challenge.dispatch import GridChargeContext as GridChargeContext
    from solar_challenge.dispatch import compute_grid_charge_power_kw as compute_grid_charge_power_kw
    from solar_challenge.dispatch import SelfConsumptionStrategy as SelfConsumptionStrategy
    from solar_challenge.dispatch import TOUOptimizedStrategy as TOUOptimizedStrategy
    from solar_challenge.dispatch import PeakShavingStrategy as PeakShavingStrategy
    from solar_challenge.dispatch import TariffPeriod as DispatchTariffPeriod  # alias (collision)
    # battery
    from solar_challenge.battery import Battery as Battery
    from solar_challenge.battery import BatteryConfig as BatteryConfig
    from solar_challenge.battery import compute_soh as compute_soh
    # flow
    from solar_challenge.flow import EnergyFlowResult as EnergyFlowResult
    from solar_challenge.flow import simulate_timestep as simulate_timestep
    from solar_challenge.flow import simulate_timestep_tou as simulate_timestep_tou
    from solar_challenge.flow import validate_energy_balance as validate_energy_balance
    from solar_challenge.flow import calculate_self_consumption as calculate_self_consumption
    from solar_challenge.flow import calculate_excess_pv as calculate_excess_pv
    from solar_challenge.flow import calculate_shortfall as calculate_shortfall
    # tariff
    from solar_challenge.tariff import TariffConfig as TariffConfig
    from solar_challenge.tariff import TariffPeriod as TariffPeriod
    from solar_challenge.tariff import calculate_bill as calculate_bill
    from solar_challenge.tariff import FlatRateTariff as FlatRateTariff
    # seg
    from solar_challenge.seg import SEGTariff as SEGTariff
    from solar_challenge.seg import resolve_seg_tariff as resolve_seg_tariff
    from solar_challenge.seg import calculate_seg_revenue as calculate_seg_revenue
    from solar_challenge.seg import SEG_PRESETS as SEG_PRESETS
    # gridservices
    from solar_challenge.gridservices import GridServicesRateBand as GridServicesRateBand
    from solar_challenge.gridservices import GridServicesRateBands as GridServicesRateBands
    from solar_challenge.gridservices import resolve_grid_services_rate_band as resolve_grid_services_rate_band
    from solar_challenge.gridservices import EventWindow as EventWindow
    from solar_challenge.gridservices import GridServicesEventsConfig as GridServicesEventsConfig
    from solar_challenge.gridservices import GridServicesAtEvents as GridServicesAtEvents
    from solar_challenge.gridservices import compute_fleet_spare_capacity_kw as compute_fleet_spare_capacity_kw
    from solar_challenge.gridservices import compute_grid_services_at_events as compute_grid_services_at_events
    from solar_challenge.gridservices import GRID_SERVICES_RATE_BANDS as GRID_SERVICES_RATE_BANDS
    from solar_challenge.gridservices import DEFAULT_EVENT_WINDOWS as DEFAULT_EVENT_WINDOWS
    # community
    from solar_challenge.community import CommunityConfig as CommunityConfig
    from solar_challenge.community import CommunityBillingConfig as CommunityBillingConfig
    from solar_challenge.community import CommunityResults as CommunityResults
    from solar_challenge.community import simulate_community as simulate_community
    from solar_challenge.community import validate_community_balance as validate_community_balance
    # pv
    from solar_challenge.pv import PVConfig as PVConfig
    from solar_challenge.pv import simulate_pv_output as simulate_pv_output
    from solar_challenge.pv import create_model_chain as create_model_chain
    from solar_challenge.pv import create_pv_system as create_pv_system
    from solar_challenge.pv import apply_degradation as apply_degradation
    from solar_challenge.pv import calculate_degradation_factor as calculate_degradation_factor
    from solar_challenge.pv import interpolate_to_minute_resolution as interpolate_to_minute_resolution
    # weather
    from solar_challenge.weather import get_tmy_data as get_tmy_data
    from solar_challenge.weather import WeatherCache as WeatherCache
    from solar_challenge.weather import get_weather_cache as get_weather_cache
    from solar_challenge.weather import set_weather_cache as set_weather_cache
    # load
    from solar_challenge.load import LoadConfig as LoadConfig
    from solar_challenge.load import OFGEM_TDCV_BY_OCCUPANTS as OFGEM_TDCV_BY_OCCUPANTS
    from solar_challenge.load import ELEXON_PROFILE_CLASS_1 as ELEXON_PROFILE_CLASS_1
    from solar_challenge.load import SEASONAL_FACTORS as SEASONAL_FACTORS
    # location
    from solar_challenge.location import Location as Location

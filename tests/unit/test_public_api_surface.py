"""The contract of solar_challenge's public surface: what `import solar_challenge` serves, and the frozen forms a consumer builds against.

Its sections, in order, each under a `# ===` banner; a `# ---` banner opens a part of one:

- The frozen forms: FROZEN_SURFACE, FROZEN_CLOSURE and FROZEN_MEMBERS, the locks holding
  the package to them, and the member guards, which accept the writes to self that
  REVIEWED_COMPUTED_NAME_WRITES lists.  A surface change edits the frozen tables' rows,
  and adds its 'Unreleased on main' line to docs/domain-library-consumption.md in the
  same commit.
- The drift report: how a failing lock names each drifted path with its frozen and
  current forms.
- Name resolution: every exported name resolves to its typed import, the object the
  package's `if TYPE_CHECKING:` block imports under that name; dir() lists the exported
  names, and an unknown name raises AttributeError; and EXPECTED_KIND's three names
  resolve to the kind their spelling misleads about.
- The runtime tables, __all__, _SYMBOL_MODULE and _SOURCE_NAME, agree at import.
- The package imports without pvlib.
"""

import abc
import ast
import enum
import functools
import inspect
import json
import subprocess
import sys
import types
import typing
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path

import pytest

import solar_challenge
import solar_challenge.dispatch as _dispatch
import solar_challenge.tariff as _tariff
from tests._surface_forms import (
    member_forms,
    signature_closure,
    surface_form,
    undeclared_attributes,
    unset_attributes,
)


# ===========================================================================
# The frozen forms, and the locks holding the package to them
# ===========================================================================


# ---------------------------------------------------------------------------
# The public names, each with its frozen surface form
#
# The keys are grouped by origin module.  Each value is the name's
# surface_form (tests/_surface_forms.py): a class's or routine's signature, a
# dataclass's following its kind, e.g. 'dataclass[eq, frozen] (...)'; an Enum's
# members, aliases included; or a constant's type, then a mapping's entries or a
# list's or tuple's items, e.g. 'dict {1: float}'.  Any add/remove to __all__
# must be reflected in the keys, and any change to a name's form in its value;
# the tests below fail naming the drifted symbol(s).  Each value stays on one
# line, so the current form a failure prints pastes in verbatim.
# ---------------------------------------------------------------------------
FROZEN_SURFACE: dict[str, str] = {
    # --- finance / bill engine (finance.py) ---
    "bill": "(*, period_days: float, generation_kwh: float, demand_kwh: float, self_consumption_kwh: float, import_kwh: float, import_cost_gbp: float, baseline_import_cost_gbp: float, finance: 'FinanceConfig') -> BillBreakdown",
    "householder_bill": "(summary: 'SummaryStatistics', annual_self_consumption_kwh: float, finance: 'FinanceConfig', simulation_days: int) -> BillBreakdown",
    "solve_cost_recovery_rate": "(scenario: 'ScenarioConfig', finance: 'FinanceConfig', *, simulate: Optional[Callable[['FleetConfig', pd.Timestamp, pd.Timestamp], 'FleetResults']] = None) -> 'CostRecoverySolution'",
    "bill_distribution": "(summaries: Sequence['SummaryStatistics'], finance: 'FinanceConfig', simulation_days: int) -> BillDistribution",
    "BillBreakdown": "dataclass[eq, frozen] (standing_charge_gbp: float, import_cost_gbp: float, own_use_payment_gbp: float, vat_gbp: float, total_outlay_gbp: float, own_use_vat_gbp: float, cbs_amount_due_gbp: float, self_consumption_saving_gbp: float, baseline_bill_gbp: float, saving_vs_baseline_gbp: float, saving_pct: float, self_consumption_fraction: float) -> None",
    "BillDistribution": "dataclass[eq, frozen] (representative: BillBreakdown, per_home_net_bill_gbp: tuple[float, ...], min_gbp: float, mean_gbp: float, median_gbp: float, max_gbp: float) -> None",
    "CostRecoverySolution": "dataclass[eq, frozen] (own_use_rate_pence_per_kwh: float, outlay: 'BillDistribution', representative_outlay_gbp: float, net_surplus_per_home_per_year_gbp: float, saving_vs_baseline_gbp: float, saving_pct: float, feasible: bool, binding: str) -> None",
    "FinanceConfig": "dataclass[eq, frozen] (standing_charge_pence_per_day: float, vat_rate: float = 0.05, retail_baseline_rate_pence_per_kwh: float = 23.0, self_consumption_override: Optional[float] = None, pv_cost_per_kwp_gbp: float = 1000.0, roof_fit_cost_gbp: float = 1000.0, battery_cost_per_kwh_gbp: float = 250.0, inverter_cost_per_kw_gbp: float = 0.0, grant_gbp: float = 250000.0, equity_fraction: float = 0.75, loan_term_years: int = 15, loan_rate: float = 0.07, opex_per_home_per_year_gbp: float = 131.0, asset_life_years: int = 25, own_use_rate_pence_per_kwh: float = 15.0, retained_cash_floor_per_home_per_year_gbp: float = 27.0, grid_services_income_per_kw_per_year_gbp: float = 0.0, grid_services_model: str = 'flat', grid_services_events: Optional['GridServicesEventsConfig'] = None) -> None",
    # --- signature-closure types ---
    "SummaryStatistics": "dataclass[eq] (total_generation_kwh: float, total_demand_kwh: float, total_self_consumption_kwh: float, total_grid_import_kwh: float, total_grid_export_kwh: float, total_battery_charge_kwh: float, total_battery_discharge_kwh: float, peak_generation_kw: float, peak_demand_kw: float, self_consumption_ratio: float, grid_dependency_ratio: float, export_ratio: float, simulation_days: int, total_import_cost_gbp: float, total_export_revenue_gbp: float, net_cost_gbp: float, strategy_name: str = 'self_consumption', seg_revenue_gbp: float | None = None, total_heat_pump_load_kwh: float | None = None, peak_heat_pump_load_kw: float | None = None, heat_pump_load_ratio: float | None = None, total_grid_charge_cost_gbp: float = 0.0, total_grid_charge_kwh: float = 0.0, window: SimulationWindow | None = None) -> None",
    "ScenarioConfig": "dataclass[eq, frozen] (name: str, period: SimulationPeriod, description: str = '', location: Location | None = None, homes: tuple[HomeConfig, ...] = (), home: HomeConfig | None = None, output: OutputConfig | None = None, seg_tariff_pence_per_kwh: float | None = None, tariff_config: TariffConfig | None = None, finance: FinanceConfig | None = None) -> None",
    "FleetConfig": "dataclass[eq] (homes: list[HomeConfig] = <factory>, name: str = '') -> None",
    "FleetResults": "dataclass[eq] (per_home_results: list[SimulationResults], home_configs: list[HomeConfig]) -> None",
    # --- dispatch (dispatch.py) ---
    "DispatchStrategy": "()",
    "DispatchDecision": "dataclass[eq, frozen] (charge_kw: float, discharge_kw: float, grid_charge_kw: float = 0.0) -> None",
    "GridChargeContext": "dataclass[eq, frozen] (current_rate: float, peak_rate: float, is_cheap_period: bool, target_soc_kwh: float, max_charge_kw: float, round_trip_efficiency: float, charge_efficiency: float) -> None",
    "compute_grid_charge_power_kw": "(ctx: GridChargeContext, *, battery_soc_kwh: float, pv_charge_power_kw: float, timestep_minutes: float) -> float",
    "SelfConsumptionStrategy": "()",
    "TOUOptimizedStrategy": "(peak_hours: list[tuple[int, int]]) -> None",
    "PeakShavingStrategy": "(import_limit_kw: float) -> None",
    "DispatchTariffPeriod": "PEAK='peak', OFF_PEAK='off_peak'",
    # --- battery (battery.py) ---
    "Battery": "(config: BatteryConfig, initial_soc_kwh: float | None = None, min_soc_fraction: float | None = None, max_soc_fraction: float | None = None, charge_efficiency: float | None = None, discharge_efficiency: float | None = None) -> None",
    "BatteryConfig": "dataclass[eq, frozen] (capacity_kwh: float, max_charge_kw: float = 2.5, max_discharge_kw: float = 2.5, name: str = '', dispatch_strategy: SelfConsumptionStrategyConfig | TOUOptimizedStrategyConfig | PeakShavingStrategyConfig | None = None, grid_charging: GridChargeConfig | None = None, min_soc_fraction: float = 0.1, max_soc_fraction: float = 0.9, charge_efficiency: float = 0.975, discharge_efficiency: float = 0.975, efficiency: float | None = None, system_age_years: float = 0.0, calendar_fade_rate_per_year: float = 0.02, cycle_fade_per_equivalent_full_cycle: float = 5e-05, soh_floor: float = 0.5, soh: float | None = None) -> None",
    "compute_soh": "(system_age_years: float, cumulative_throughput_kwh: float, usable_capacity_kwh: float, params: BatteryConfig) -> float",
    # --- flow (flow.py) ---
    "EnergyFlowResult": "dataclass[eq] (generation: float, demand: float, self_consumption: float, battery_charge: float, battery_discharge: float, grid_export: float, grid_import: float, battery_soc: float, grid_charge: float = 0.0) -> None",
    "simulate_timestep": "(generation_kw: float, demand_kw: float, battery: Battery | None, timestep_minutes: float = 1.0, timestamp: datetime | None = None, strategy: DispatchStrategy | None = None, *, tariff: TariffConfig | None = None) -> EnergyFlowResult",
    "simulate_timestep_tou": "(generation_kw: float, demand_kw: float, battery: Battery | None, timestamp: Timestamp, tariff: TariffConfig, timestep_minutes: float = 1.0) -> EnergyFlowResult",
    "validate_energy_balance": "(result: EnergyFlowResult, tolerance: float = 0.001) -> bool",
    "calculate_self_consumption": "(generation: Series, demand: Series) -> Series",
    "calculate_excess_pv": "(generation: Series, demand: Series) -> Series",
    "calculate_shortfall": "(generation: Series, demand: Series) -> Series",
    # --- tariff (tariff.py) ---
    "TariffConfig": "dataclass[eq, frozen] (periods: tuple[TariffPeriod, ...], name: str = '') -> None",
    "TariffPeriod": "dataclass[eq, frozen] (start_time: str, end_time: str, rate_per_kwh: float, name: str = '') -> None",
    "calculate_bill": "(energy_kwh: Series, tariff: TariffConfig) -> float",
    "FlatRateTariff": "(rate_per_kwh: float, name: str = '') -> TariffConfig",
    # --- seg (seg.py) ---
    "SEGTariff": "dataclass[eq, frozen] (name: str, rate_pence_per_kwh: float) -> None",
    "resolve_seg_tariff": "(name: str) -> SEGTariff",
    "calculate_seg_revenue": "(export_kwh: float, tariff: SEGTariff) -> float",
    "SEG_PRESETS": "dict {'Octopus': SEGTariff, 'British Gas': SEGTariff, 'EDF': SEGTariff, 'E.ON': SEGTariff, 'Scottish Power': SEGTariff, 'OVO': SEGTariff}",
    # --- gridservices (gridservices.py) ---
    "GridServicesRateBand": "dataclass[eq, frozen] (availability_gbp_per_kw_per_event: float, utilisation_gbp_per_mwh: float, provenance: str = '', flat_gbp_per_kw_per_year: float = 0.0) -> None",
    "GridServicesRateBands": "dataclass[eq, frozen] (low: GridServicesRateBand, central: GridServicesRateBand, high: GridServicesRateBand) -> None",
    "resolve_grid_services_rate_band": "(band: str) -> GridServicesRateBand",
    "EventWindow": "dataclass[eq, frozen] (months: tuple[int, ...], weekdays: tuple[int, ...], hours: tuple[int, ...], events_per_year: int, event_hours: float) -> None",
    "GridServicesEventsConfig": "dataclass[eq, frozen] (band: str = 'central', event_windows: tuple[EventWindow, ...] = (EventWindow(months=(11, 12, 1, 2), weekdays=(0, 1, 2, 3, 4), hours=(16, 17, 18), events_per_year=12, event_hours=3.0),), aggregator_share: float = 0.25, utilisation_factor: float = 0.6, availability_gbp_per_kw_per_event: float | None = None, utilisation_gbp_per_mwh: float | None = None) -> None",
    "GridServicesAtEvents": "dataclass[eq, frozen] (annual_income_gbp: float, per_window_avail_kw: tuple[float, ...], per_window_income_gbp: tuple[float, ...]) -> None",
    "compute_fleet_spare_capacity_kw": "(fleet_results: FleetResults, windows: tuple[EventWindow, ...]) -> tuple[float, ...]",
    "compute_grid_services_at_events": "(fleet_results: FleetResults, cfg: GridServicesEventsConfig) -> GridServicesAtEvents",
    "GRID_SERVICES_RATE_BANDS": "GridServicesRateBands",
    "DEFAULT_EVENT_WINDOWS": "tuple [EventWindow]",
    # --- community (community.py) ---
    "CommunityConfig": "dataclass[eq, frozen] (sharing_mode: Literal['p2p', 'community_battery'], community_battery: Optional[BatteryConfig] = None, billing: Optional[CommunityBillingConfig] = None) -> None",
    "CommunityBillingConfig": "dataclass[eq, frozen] (tariff: Optional[TariffConfig] = None, seg_rate_pence_per_kwh: Optional[float] = None) -> None",
    "CommunityResults": "dataclass[eq] (grid_import: pd.Series, grid_export: pd.Series, battery_charge: pd.Series, battery_discharge: pd.Series, battery_soc: pd.Series, fleet_results: 'FleetResults', sharing_mode: Literal['p2p', 'community_battery'], baseline_net_cost_gbp: Optional[float] = None, community_net_cost_gbp: Optional[float] = None, community_savings_gbp: Optional[float] = None) -> None",
    "simulate_community": "(fleet_results: 'FleetResults', config: CommunityConfig, *, validate_balance: bool = True) -> CommunityResults",
    "validate_community_balance": "(fleet_results: 'FleetResults', community_results: CommunityResults, tolerance: float = 0.001) -> bool",
    # --- pv (pv.py) ---
    "PVConfig": "dataclass[eq, frozen] (capacity_kw: float, azimuth: float = 180.0, tilt: float = 35.0, name: str = '', module_efficiency: float | None = None, temperature_coefficient: float | None = None, custom_module_params: dict[str, float] | None = None, inverter_efficiency: float = 0.96, inverter_capacity_kw: float | None = None, custom_inverter_params: dict[str, float] | None = None, system_age_years: float = 0.0, degradation_rate_per_year: float = 0.005, system_losses: float = 0.14075660688264469) -> None",
    "simulate_pv_output": "(config: PVConfig, location: Location, weather_data: DataFrame) -> Series",
    "create_model_chain": "(config: PVConfig, location: Location) -> ModelChain",
    "create_pv_system": "(config: PVConfig) -> PVSystem",
    "apply_degradation": "(generation: Series, system_age_years: float, degradation_rate_per_year: float = 0.005) -> Series",
    "calculate_degradation_factor": "(system_age_years: float, degradation_rate_per_year: float = 0.005) -> float",
    "interpolate_to_minute_resolution": "(hourly_power: Series) -> Series",
    # --- weather (weather.py) ---
    "get_tmy_data": "(location: Location, use_cache: bool = True) -> DataFrame",
    "WeatherCache": "(cache_dir: Path | None = None) -> None",
    "get_weather_cache": "() -> WeatherCache",
    "set_weather_cache": "(cache: WeatherCache | None) -> None",
    "WeatherProvider": "(*args, **kwargs)",
    "PvgisTmy": "dataclass[eq, frozen] (cache: WeatherCache | None) -> None",
    "PrefetchedWeather": "dataclass[frozen] (frames: Mapping[Location, DataFrame]) -> None",
    # --- load (load.py) ---
    "LoadConfig": "dataclass[eq, frozen] (annual_consumption_kwh: float | None = None, household_occupants: int = 3, name: str = '', use_stochastic: bool = True, seed: int | None = None) -> None",
    "OFGEM_TDCV_BY_OCCUPANTS": "dict {1: float, 2: float, 3: float, 4: float, 5: float}",
    "ELEXON_PROFILE_CLASS_1": "list [float × 48]",
    "SEASONAL_FACTORS": "dict {1: float, 2: float, 3: float, 4: float, 5: float, 6: float, 7: float, 8: float, 9: float, 10: float, 11: float, 12: float}",
    # --- location (location.py) ---
    "Location": "dataclass[eq, frozen] (latitude: float, longitude: float, timezone: str = 'Europe/London', altitude: float = 0.0, name: str = '') -> None",
}

FROZEN_SET: frozenset[str] = frozenset(FROZEN_SURFACE)


def test_all_equals_frozen_set() -> None:
    """__all__ lists exactly FROZEN_SURFACE's names; the message names each name only one of them lists.

    A set comparison needs no count, because importing the package refuses a name
    __all__ lists twice (test_importing_the_package_refuses_tables_that_disagree).
    """
    actual = set(solar_challenge.__all__)
    diff = actual.symmetric_difference(FROZEN_SET)
    assert actual == FROZEN_SET, (
        f"__all__ has drifted from FROZEN_SET.  "
        f"Symmetric difference: {sorted(diff)}"
    )


def test_all_has_no_cli_names() -> None:
    """No name of __all__ is get_cli_app or starts with cli or web: the CLI and the web app ship unfrozen."""
    cli_names = [
        name
        for name in solar_challenge.__all__
        if name == "get_cli_app" or name.startswith(("cli", "web"))
    ]
    assert not cli_names, (
        f"__all__ lists names of the CLI or the web app, which ship unfrozen: {cli_names}"
    )


# ---------------------------------------------------------------------------
# Every exported name keeps the surface form FROZEN_SURFACE pins
# ---------------------------------------------------------------------------


def test_every_exported_signature_matches_frozen_surface() -> None:
    """Every name in __all__ has the surface form FROZEN_SURFACE pins.

    Fails once, naming each drifted symbol with its frozen and current forms.  A name
    absent from FROZEN_SURFACE counts as drifted, so its current form is printed ready to
    paste; a name missing from __all__ is test_all_equals_frozen_set's to report.
    """
    current_forms = {
        name: surface_form(getattr(solar_challenge, name))
        for name in solar_challenge.__all__
    }
    drifted = {
        name: form
        for name, form in current_forms.items()
        if form != FROZEN_SURFACE.get(name)
    }
    assert not drifted, _drift_message("FROZEN_SURFACE", FROZEN_SURFACE, drifted)


# ---------------------------------------------------------------------------
# The classes outside __all__ that the frozen surface names, directly or
# through another such class, each with its frozen surface form
#
# A consumer needs them to use exported names: a ScenarioConfig is built from a
# SimulationPeriod and HomeConfigs, and FleetResults.per_home_results holds
# SimulationResults.  Each key is the path below solar_challenge of the module
# that defines the class, then its qualified name, e.g. 'home.HomeConfig', in
# path order; each value is the class's surface_form, on one line.
# FROZEN_MEMBERS pins their members.  A class leaves this table when it joins
# __all__.
# ---------------------------------------------------------------------------
FROZEN_CLOSURE: dict[str, str] = {
    "config.OutputConfig": "dataclass[eq] (csv_path: str | None = None, include_minute_data: bool = True, include_summary: bool = True, aggregation: str = 'minute') -> None",
    "config.SimulationPeriod": "dataclass[eq] (start_date: str | Timestamp, end_date: str | Timestamp) -> None",
    "dispatch.GridChargeConfig": "dataclass[eq, frozen] (target_soc_fraction: float = 0.9) -> None",
    "dispatch.PeakShavingStrategyConfig": "dataclass[eq, frozen] (import_limit_kw: float) -> None",
    "dispatch.SelfConsumptionStrategyConfig": "dataclass[eq, frozen] () -> None",
    "dispatch.TOUOptimizedStrategyConfig": "dataclass[eq, frozen] (peak_hours: tuple[tuple[int, int], ...]) -> None",
    "ev.EVConfig": "dataclass[eq, frozen] (charger_type: str, arrival_hour: int = 18, departure_hour: int = 7, required_charge_kwh: float = 35.0, smart_charging_mode: str = 'none', name: str = '') -> None",
    "heat_pump.HeatPumpConfig": "dataclass[eq, frozen] (heat_pump_type: Literal['ASHP', 'GSHP'], thermal_capacity_kw: float = 8.0, annual_heat_demand_kwh: float = 8000.0, name: str = '') -> None",
    "home.HomeConfig": "dataclass[eq, frozen] (pv_config: PVConfig, load_config: LoadConfig, battery_config: BatteryConfig | None = None, heat_pump_config: HeatPumpConfig | None = None, ev_config: EVConfig | None = None, location: Location = Location(latitude=51.45, longitude=-2.58, timezone='Europe/London', altitude=11.0, name='Bristol, UK'), name: str = '', tariff_config: TariffConfig | None = None, dispatch_strategy: str = 'greedy', seg_tariff: SEGTariff | None = None) -> None",
    "home.SimulationResults": "dataclass[eq, frozen] (generation: Series, demand: Series, self_consumption: Series, battery_charge: Series, battery_discharge: Series, battery_soc: Series, grid_import: Series, grid_export: Series, import_cost: Series, export_revenue: Series, tariff_rate: Series, strategy_name: str = 'self_consumption', heat_pump_load: Series | None = None, grid_charge_cost: Series | None = None, grid_charge: Series | None = None) -> None",
    "timebase.LocalDay": "dataclass[frozen] (date: date, rows: DatetimeIndex) -> None",
    "timebase.SimulationWindow": "dataclass[eq, frozen] (first_day: date, last_day: date, cadence: timedelta, timezone: str | None = None) -> None",
}

_SUBMODULE_PREFIX = f"{solar_challenge.__name__}."


@functools.cache
def _closure_classes() -> Mapping[str, type]:
    """The classes outside __all__ that the frozen surface names, directly or through another such class, by path in path order.

    They are the signature_closure, within solar_challenge, of every object in __all__.
    The modules it reads are fixed for the run, so it is computed once and handed out
    read-only.
    """
    exported = [getattr(solar_challenge, name) for name in solar_challenge.__all__]
    by_path = {
        f"{cls.__module__.removeprefix(_SUBMODULE_PREFIX)}.{cls.__qualname__}": cls
        for cls in signature_closure(exported, solar_challenge.__name__)
    }
    return types.MappingProxyType(dict(sorted(by_path.items())))


def test_every_class_the_frozen_surface_names_matches_frozen_closure() -> None:
    """Each class outside __all__ that the frozen surface names has the surface form FROZEN_CLOSURE pins.

    Fails once, naming each drifted class with its frozen and current forms, in path
    order.  A class a pinned form newly names counts as drifted, so its current form is
    printed ready to paste; a pinned class no form names any longer is listed last, its
    current form reading (not named by the frozen surface).
    """
    current = {path: surface_form(cls) for path, cls in _closure_classes().items()}
    drifted = _drifted(
        FROZEN_CLOSURE, current, absent="(not named by the frozen surface)"
    )
    assert not drifted, _drift_message("FROZEN_CLOSURE", FROZEN_CLOSURE, drifted)


# ---------------------------------------------------------------------------
# Each pinned class's public members, with their frozen forms
#
# A pinned class is an exported class or a FROZEN_CLOSURE class.  Keys are the
# pinned classes' paths below solar_challenge, then member names: exported
# classes first, in __all__ order, then closure classes in path order, and
# members in the order member_forms lists them, the order a failure lists
# drifted members in.  Each value is the member's form as member_forms spells
# it (tests/_surface_forms.py).  A class with no public member has no entry.
# Each value stays on one line, so the current form a failure prints pastes in
# verbatim.
# ---------------------------------------------------------------------------
FROZEN_MEMBERS: dict[str, dict[str, str]] = {
    # --- signature-closure types ---
    "SummaryStatistics": {
        "total_pv_charge_kwh": "property (self) -> float",
        "total_direct_self_consumption_kwh": "property (self) -> float",
        "total_grid_to_demand_kwh": "property (self) -> float",
    },
    "ScenarioConfig": {
        "is_fleet": "property (self) -> bool",
        "get_location": "(self) -> Location",
        "simulated_homes": "(self) -> tuple[HomeConfig, ...]",
        "map_homes": "(self, transform: Callable[[HomeConfig], HomeConfig]) -> ScenarioConfig",
    },
    "FleetConfig": {
        "create_uniform": "classmethod (cls, n_homes: int, pv_config: PVConfig, load_config: LoadConfig, battery_config: BatteryConfig | None = None, location: Location = Location(latitude=51.45, longitude=-2.58, timezone='Europe/London', altitude=11.0, name='Bristol, UK'), name: str = '') -> FleetConfig",
        "create_heterogeneous": "classmethod (cls, pv_capacities_kw: list[float], battery_capacities_kwh: list[float | None], annual_consumptions_kwh: list[float], location: Location = Location(latitude=51.45, longitude=-2.58, timezone='Europe/London', altitude=11.0, name='Bristol, UK'), name: str = '') -> FleetConfig",
    },
    "FleetResults": {
        "get_aggregate_series": "(self, series_name: str) -> Series",
        "total_generation": "property (self) -> Series",
        "total_demand": "property (self) -> Series",
        "total_grid_import": "property (self) -> Series",
        "total_grid_export": "property (self) -> Series",
        "total_self_consumption": "property (self) -> Series",
        "to_aggregate_dataframe": "(self) -> DataFrame",
    },
    # --- dispatch (dispatch.py) ---
    "DispatchStrategy": {
        "name": "abstract property (self) -> str",
        "decide_action": "abstract (self, timestamp: datetime, generation_kw: float, demand_kw: float, battery_soc_kwh: float, battery_capacity_kwh: float, timestep_minutes: float = 1.0, *, grid_charge_ctx: GridChargeContext | None = None) -> DispatchDecision",
    },
    "SelfConsumptionStrategy": {
        "name": "property (self) -> str",
        "decide_action": "(self, timestamp: datetime, generation_kw: float, demand_kw: float, battery_soc_kwh: float, battery_capacity_kwh: float, timestep_minutes: float = 1.0, *, grid_charge_ctx: GridChargeContext | None = None) -> DispatchDecision",
    },
    "TOUOptimizedStrategy": {
        "name": "property (self) -> str",
        "decide_action": "(self, timestamp: datetime, generation_kw: float, demand_kw: float, battery_soc_kwh: float, battery_capacity_kwh: float, timestep_minutes: float = 1.0, *, grid_charge_ctx: GridChargeContext | None = None) -> DispatchDecision",
    },
    "PeakShavingStrategy": {
        "name": "property (self) -> str",
        "decide_action": "(self, timestamp: datetime, generation_kw: float, demand_kw: float, battery_soc_kwh: float, battery_capacity_kwh: float, timestep_minutes: float = 1.0, *, grid_charge_ctx: GridChargeContext | None = None) -> DispatchDecision",
    },
    # --- battery (battery.py) ---
    "Battery": {
        "config": "attribute BatteryConfig",
        "min_soc_fraction": "property[settable] (self) -> float",
        "max_soc_fraction": "property[settable] (self) -> float",
        "charge_efficiency": "property[settable] (self) -> float",
        "discharge_efficiency": "property[settable] (self) -> float",
        "soh": "property (self) -> float",
        "effective_capacity_kwh": "property (self) -> float",
        "soc_kwh": "property (self) -> float",
        "soc_fraction": "property (self) -> float",
        "min_soc_kwh": "property (self) -> float",
        "max_soc_kwh": "property (self) -> float",
        "grid_charge_target_kwh": "property (self) -> float | None",
        "usable_capacity_kwh": "property (self) -> float",
        "available_charge_capacity_kwh": "property (self) -> float",
        "available_discharge_capacity_kwh": "property (self) -> float",
        "max_charge_kw": "property (self) -> float",
        "charge": "(self, power_kw: float, duration_minutes: float) -> float",
        "discharge": "(self, power_kw: float, duration_minutes: float) -> float",
    },
    "BatteryConfig": {
        "nominal_usable_capacity_kwh": "property (self) -> float",
        "default_5kwh": "classmethod (cls) -> BatteryConfig",
    },
    # --- tariff (tariff.py) ---
    "TariffConfig": {
        "peak_rate": "cached_property (self) -> float",
        "mean_period_rate": "cached_property (self) -> float",
        "cheap_minutes_of_day": "cached_property (self) -> frozenset[int]",
        "get_rate": "(self, timestamp: Timestamp) -> float",
        "is_cheap_at": "(self, timestamp: datetime) -> bool",
        "flat_rate": "classmethod (cls, rate_per_kwh: float, name: str = '') -> TariffConfig",
        "economy_7": "classmethod (cls, off_peak_rate: float = 0.09, peak_rate: float = 0.25, off_peak_start: str = '00:30', off_peak_end: str = '07:30') -> TariffConfig",
        "economy_10": "classmethod (cls, off_peak_rate: float = 0.08, peak_rate: float = 0.27, night_start: str = '00:00', night_end: str = '05:00', afternoon_start: str = '13:00', afternoon_end: str = '16:00', evening_start: str = '20:00', evening_end: str = '22:00') -> TariffConfig",
    },
    "TariffPeriod": {
        "get_start_time": "(self) -> time",
        "get_end_time": "(self) -> time",
        "matches_time": "(self, timestamp: Timestamp) -> bool",
    },
    # --- gridservices (gridservices.py) ---
    "GridServicesRateBands": {
        "resolve": "(self, band: str) -> GridServicesRateBand",
    },
    "EventWindow": {
        "mask": "(self, index: DatetimeIndex) -> Series",
    },
    "GridServicesEventsConfig": {
        "annual_income_gbp": "(self, fleet_results: FleetResults) -> float",
    },
    # --- pv (pv.py) ---
    "PVConfig": {
        "effective_inverter_capacity_kw": "property (self) -> float",
        "default_4kw": "classmethod (cls) -> PVConfig",
    },
    # --- weather (weather.py) ---
    "WeatherCache": {
        "cache_dir": "attribute Path",
        "get": "(self, prefix: str, location: Location, start_date: Timestamp | None = None, end_date: Timestamp | None = None) -> DataFrame | None",
        "put": "(self, data: DataFrame, prefix: str, location: Location, start_date: Timestamp | None = None, end_date: Timestamp | None = None) -> None",
        "clear": "(self) -> int",
        "invalidate": "(self, prefix: str, location: Location, start_date: Timestamp | None = None, end_date: Timestamp | None = None) -> bool",
    },
    "WeatherProvider": {
        "get": "(self, location: Location) -> DataFrame",
    },
    "PvgisTmy": {
        "get": "(self, location: Location) -> DataFrame",
    },
    "PrefetchedWeather": {
        "get": "(self, location: Location) -> DataFrame",
        "fetch": "classmethod (cls, weather: WeatherProvider, locations: Iterable[Location]) -> PrefetchedWeather",
    },
    # --- load (load.py) ---
    "LoadConfig": {
        "get_annual_consumption": "(self) -> float",
    },
    # --- location (location.py) ---
    "Location": {
        "BRISTOL_LAT": "float",
        "BRISTOL_LON": "float",
        "BRISTOL_ALT": "float",
        "bristol": "classmethod (cls) -> Location",
    },
    # --- classes outside __all__ (FROZEN_CLOSURE) ---
    "config.SimulationPeriod": {
        "get_start_timestamp": "(self, timezone: str = 'Europe/London') -> Timestamp",
        "get_end_timestamp": "(self, timezone: str = 'Europe/London') -> Timestamp",
    },
    "dispatch.PeakShavingStrategyConfig": {
        "strategy_type": "attribute Literal['peak_shaving']",
    },
    "dispatch.SelfConsumptionStrategyConfig": {
        "strategy_type": "attribute Literal['self_consumption']",
    },
    "dispatch.TOUOptimizedStrategyConfig": {
        "strategy_type": "attribute Literal['tou_optimized']",
    },
    "ev.EVConfig": {
        "get_charger_power_kw": "(self) -> float",
        "get_available_charging_hours": "(self) -> float",
    },
    "heat_pump.HeatPumpConfig": {
        "default_ashp": "classmethod (cls) -> HeatPumpConfig",
        "default_gshp": "classmethod (cls) -> HeatPumpConfig",
    },
    "home.SimulationResults": {
        "window": "property (self) -> SimulationWindow",
        "per_minute_amounts": "(self) -> DataFrame",
        "total_amounts": "(self) -> dict[str, float]",
        "to_dataframe": "(self) -> DataFrame",
        "from_dataframe": "classmethod (cls, frame: DataFrame, *, strategy_name: str) -> SimulationResults",
    },
    "timebase.LocalDay": {
        "minute_of_day": "(self) -> ndarray",
        "instant": "(self, minute_of_day: int) -> Timestamp",
    },
    "timebase.SimulationWindow": {
        "of_index": "classmethod (cls, index: Index) -> SimulationWindow",
        "days": "property (self) -> int",
        "year_days": "property (self) -> float",
        "annualisation_scale": "property (self) -> float",
        "extrapolated": "property (self) -> bool",
        "step_hours": "property (self) -> float",
        "step_minutes": "property (self) -> float",
        "row_energy_kwh": "(self, power_kw: Series) -> Series",
        "energy_kwh": "(self, power_kw: Series) -> float",
        "rows": "(self) -> DatetimeIndex",
        "local_days": "(self) -> Iterator[LocalDay]",
    },
}


def _exported_classes() -> dict[str, type]:
    """The class-valued names of solar_challenge.__all__, in __all__ order."""
    exported = {name: getattr(solar_challenge, name) for name in solar_challenge.__all__}
    return {name: obj for name, obj in exported.items() if inspect.isclass(obj)}


def _pinned_classes() -> dict[str, type]:
    """Each pinned class by its path below solar_challenge: the exported classes by export name, in __all__ order, then the classes outside __all__ that the frozen surface names, in path order."""
    return {**_exported_classes(), **_closure_classes()}


def _forms_by_member_path(
    forms_by_class: Mapping[str, Mapping[str, str]],
) -> dict[str, str]:
    """Flatten *forms_by_class*, keyed by class path, to {"path.member": form}, a path built for display and comparison, never split."""
    return {
        f"{class_path}.{member}": form
        for class_path, forms in forms_by_class.items()
        for member, form in forms.items()
    }


def test_every_pinned_class_member_matches_frozen_members() -> None:
    """Every pinned class's public members have the forms FROZEN_MEMBERS pins.

    Fails once, naming each added, changed or removed member with its frozen and current
    forms, in pinned-class order and, within a class, the order member_forms lists its
    members, removed members last.  An added member's current form is printed ready to
    paste; a removed member's current form reads (removed).
    """
    frozen = _forms_by_member_path(FROZEN_MEMBERS)
    current = _forms_by_member_path(
        {path: member_forms(cls) for path, cls in _pinned_classes().items()}
    )
    drifted = _drifted(frozen, current, absent="(removed)")
    assert not drifted, _drift_message("FROZEN_MEMBERS", frozen, drifted)


_STDLIB_BASES: tuple[type, ...] = (object, abc.ABC, enum.Enum, typing.Protocol, typing.Generic)


def test_pinned_classes_inherit_only_from_pinned_classes() -> None:
    """A pinned class's bases are pinned classes or _STDLIB_BASES.

    FROZEN_MEMBERS pins a member under the pinned class whose own body defines it.
    """
    classes = _pinned_classes()
    pinned = set(classes.values())
    foreign_bases = [
        f"{path} <- {base.__module__}.{base.__qualname__}"
        for path, cls in classes.items()
        for base in cls.__mro__[1:]
        if base not in pinned and base not in _STDLIB_BASES
    ]
    assert not foreign_bases, (
        "Pinned classes, those exported or outside __all__ and named by the frozen "
        f"surface, inherit from classes that are neither: {foreign_bases}. "
        "member_forms reads each class's own body, so a public member defined on such a "
        "base escapes FROZEN_MEMBERS. Export the base, move its public members into the "
        "pinned class, or widen the member lock."
    )


# ---------------------------------------------------------------------------
# The writes to self under a computed name that a reviewer has checked
#
# undeclared_attributes and unset_attributes cannot tell which names a write to
# self under a computed name sets, so they refuse one unless it is reviewed
# here.  Keys are pinned-class paths, then each write's text exactly as their
# TypeError prints it, ready to paste; each value is the reviewed reason that
# every name the write sets is declared.  A new such write, in a new pinned
# class or an old one, trips the lock until someone reviews it.  An entry its
# class no longer makes raises ValueError, so drop the entry then.
# ---------------------------------------------------------------------------
REVIEWED_COMPUTED_NAME_WRITES: dict[str, dict[str, str]] = {
    "home.SimulationResults": {
        "object.__setattr__(self, name, series.rename(column))": "__post_init__ draws name from _series_columns(), which reads dataclasses.fields, so each name is a declared field by construction",
    },
}


def test_pinned_classes_declare_the_public_attributes_they_set_on_self() -> None:
    """A pinned class declares in a class body each public attribute its __init__ or __post_init__ sets on self, and sets there each one its body only declares.

    member_forms reads class bodies, so FROZEN_MEMBERS pins an instance attribute only
    once its class body declares it, e.g. `cache_dir: Path`; and a declaration that no
    __init__ or __post_init__ sets would pin a name that instances lack.

    A known gap: undeclared_attributes reads only __init__ and __post_init__, so an
    undeclared public attribute that only another method sets on self, such as a cache
    filled on first use, passes this guard though FROZEN_MEMBERS cannot pin it.
    """
    classes = _pinned_classes()
    undeclared = [
        f"{path}.{attribute}"
        for path, cls in classes.items()
        for attribute in sorted(
            undeclared_attributes(cls, reviewed=REVIEWED_COMPUTED_NAME_WRITES.get(path, {}))
        )
    ]
    unset = [
        f"{path}.{attribute}"
        for path, cls in classes.items()
        for attribute in sorted(
            unset_attributes(cls, reviewed=REVIEWED_COMPUTED_NAME_WRITES.get(path, {}))
        )
    ]
    assert not undeclared and not unset, (
        f"Public attributes set on self that no class body declares: {undeclared}. "
        "Attributes a class body declares that no __init__ or __post_init__ sets on "
        f"self: {unset}. "
        "member_forms reads class bodies, so FROZEN_MEMBERS cannot pin an attribute "
        "that is only set on self. Declare each such attribute in its class body, e.g. "
        "`cache_dir: Path`, then add its FROZEN_MEMBERS entry and its 'Unreleased on "
        "main' line in docs/domain-library-consumption.md, or make it private; and set "
        "each declared attribute in __init__ or __post_init__, or drop its declaration."
    )


def test_reviewed_computed_name_writes_name_only_pinned_classes() -> None:
    """Sync guard: every key of REVIEWED_COMPUTED_NAME_WRITES is a pinned class's path.

    The lock test passes each pinned class only its own entry, so an entry under any
    other path, stale or misspelled, would be read by nothing.
    """
    stale = REVIEWED_COMPUTED_NAME_WRITES.keys() - _pinned_classes().keys()
    assert not stale, (
        "REVIEWED_COMPUTED_NAME_WRITES names paths that are no pinned class's "
        f"(stale/misspelled?): {sorted(stale)}"
    )


# ===========================================================================
# The drift report: each path whose current form differs from its frozen one,
# printed with both forms, the current one ready to paste
# ===========================================================================


def _drift_message(
    table: str, frozen: Mapping[str, str], drifted: Mapping[str, str]
) -> str:
    """Name each path of *drifted*, a map of path to current form, with its frozen and current forms.

    *frozen* holds the forms of the table named *table*, keyed by the same paths.
    """
    symbols = "".join(
        f"\n  solar_challenge.{path}"
        f"\n    frozen:  {frozen.get(path, f'(absent from {table})')}"
        f"\n    current: {current}"
        for path, current in drifted.items()
    )
    return (
        f"Surface forms differ from {table}:{symbols}\n"
        "Every change to the frozen public API (review/briefing.yaml), an addition "
        "included, needs an 'Unreleased on main' release note in the 'Tag / release "
        "convention' section of docs/domain-library-consumption.md, landed in the same "
        f"commit as the {table} edit."
    )


def _drifted(
    frozen: Mapping[str, str], current: Mapping[str, str], *, absent: str
) -> dict[str, str]:
    """Map each path whose current form is not its frozen one to its current form.

    *current*'s paths come first, in its order, then each frozen path *current* lacks,
    whose current form reads *absent*.
    """
    missing = [path for path in frozen if path not in current]
    return {
        path: current.get(path, absent)
        for path in [*current, *missing]
        if current.get(path) != frozen.get(path)
    }


# ===========================================================================
# Name resolution: what the package resolves each name to, and what dir() lists
# ===========================================================================


# ---------------------------------------------------------------------------
# Every exported name resolves to its typed import: the object the package's
# `if TYPE_CHECKING:` block, which type checkers read, imports under that name
# ---------------------------------------------------------------------------


def _type_checking_imports() -> dict[str, tuple[str, str]]:
    """Each name the package's top-level `if TYPE_CHECKING:` block binds, mapped to
    the module it imports from and the name it imports there."""
    source = Path(solar_challenge.__file__).read_text(encoding="utf-8")
    blocks = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
    ]
    return {
        alias.asname or alias.name: (statement.module, alias.name)
        for block in blocks
        for statement in block.body
        if isinstance(statement, ast.ImportFrom) and statement.module is not None
        for alias in statement.names
    }


def test_type_checking_block_names_match_all() -> None:
    """Names bound in the TYPE_CHECKING block must equal set(__all__) plus 'Typer'.

    Reads the names the block binds through _type_checking_imports() and verifies
    they stay in sync with __all__. Adding a name to __all__ and to the lazy
    loader's map but forgetting its TYPE_CHECKING re-export would otherwise
    silently break mypy --strict for consumers without failing this package's own checks.
    """
    tc_names = set(_type_checking_imports())

    # TYPE_CHECKING block includes "Typer" for get_cli_app()'s return annotation;
    # Typer is NOT in __all__ — CLI is shipped but unfrozen.
    expected = set(solar_challenge.__all__) | {"Typer"}
    assert tc_names == expected, (
        f"TYPE_CHECKING block out of sync with __all__.\n"
        f"Extra (not in __all__ + Typer): {tc_names - expected}\n"
        f"Missing (in __all__ but not TYPE_CHECKING): {expected - tc_names}"
    )


def test_every_name_resolves_to_its_type_checking_import() -> None:
    """Each __all__ name resolves to the object the package's `if TYPE_CHECKING:`
    block imports under that name, and stays that object across accesses.

    Type checkers read that block, so the runtime and typed surfaces must agree.
    A name the block does not import is test_type_checking_block_names_match_all's
    to report.
    """
    imports = _type_checking_imports()
    misresolved: list[str] = []
    for name in solar_challenge.__all__:
        if name not in imports:
            continue
        module, source = imports[name]
        imported = getattr(import_module(module), source)
        resolved, resolved_again = getattr(solar_challenge, name), getattr(solar_challenge, name)
        if resolved is not imported or resolved_again is not imported:
            misresolved.append(f"solar_challenge.{name} is not {module}.{source}")
    assert not misresolved, (
        "Names that resolve to an object other than their TYPE_CHECKING import:\n"
        + "\n".join(misresolved)
    )


def test_tariffperiod_collision_resolved() -> None:
    """DispatchTariffPeriod and TariffPeriod are distinct objects (collision-renamed correctly).

    dispatch.TariffPeriod (Enum) is exposed as DispatchTariffPeriod.
    tariff.TariffPeriod (dataclass) is exposed as TariffPeriod.
    They must be distinct — otherwise one silently shadows the other.
    """
    assert solar_challenge.DispatchTariffPeriod is _dispatch.TariffPeriod, (
        "solar_challenge.DispatchTariffPeriod must be dispatch.TariffPeriod"
    )
    assert solar_challenge.TariffPeriod is _tariff.TariffPeriod, (
        "solar_challenge.TariffPeriod must be tariff.TariffPeriod"
    )
    assert solar_challenge.DispatchTariffPeriod is not solar_challenge.TariffPeriod, (
        "DispatchTariffPeriod and TariffPeriod must be distinct objects"
    )


# ---------------------------------------------------------------------------
# dir() lists the exported names, and an unknown name raises AttributeError
# ---------------------------------------------------------------------------


def test_unknown_attribute_raises() -> None:
    """Accessing an undefined attribute raises AttributeError."""
    with pytest.raises(AttributeError):
        _ = solar_challenge.does_not_exist


def test_dir_returns_sorted_all() -> None:
    """`dir(solar_challenge)` returns exactly sorted(__all__)."""
    assert dir(solar_challenge) == sorted(solar_challenge.__all__)


# ---------------------------------------------------------------------------
# The kind each name below resolves to, where its spelling suggests another:
# 'class', 'function' or 'constant', as _kind classifies it
# ---------------------------------------------------------------------------
EXPECTED_KIND: dict[str, str] = {
    "FlatRateTariff": "function",           # GOTCHA: CamelCase factory, NOT a class
    "GRID_SERVICES_RATE_BANDS": "constant", # GOTCHA: frozen-dataclass instance, NOT a class
    "DispatchTariffPeriod": "class",        # Enum alias — verifies clean class re-export
}


def _kind(obj: object) -> str:
    """Classify obj as 'class', 'function', or 'constant' by introspection."""
    if inspect.isclass(obj):
        return "class"
    if inspect.isroutine(obj):
        return "function"
    return "constant"


def test_expected_kind_keys_match_frozen_set() -> None:
    """Sync guard: every key in EXPECTED_KIND must exist in FROZEN_SET.

    EXPECTED_KIND is a targeted gotcha-guard (not a mirror of the full surface),
    so equality is not required — only that no stale / misspelled gotcha entry
    references a name that was removed from the public surface.
    """
    stale = set(EXPECTED_KIND) - FROZEN_SET
    assert not stale, (
        f"EXPECTED_KIND contains names not in FROZEN_SET (stale/misspelled?): "
        f"{sorted(stale)}"
    )


def test_every_expected_kind_name_resolves_to_its_kind() -> None:
    """Each EXPECTED_KIND name resolves to an object of the kind EXPECTED_KIND pins for it.

    On a failure, pytest's diff of the two dicts names each name whose kind has drifted.
    """
    assert {name: _kind(getattr(solar_challenge, name)) for name in EXPECTED_KIND} == EXPECTED_KIND


# ===========================================================================
# The runtime tables agree at import: importing the package refuses __all__,
# _SYMBOL_MODULE and _SOURCE_NAME when they disagree, naming each offender
# ===========================================================================

_IMPORT_PROBE = """\
import importlib.util
import json
import sys
from pathlib import Path

package = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "solar_challenge", package / "__init__.py", submodule_search_locations=[str(package)]
)
module = importlib.util.module_from_spec(spec)
sys.modules["solar_challenge"] = module
try:
    spec.loader.exec_module(module)
except RuntimeError as refusal:
    print(json.dumps(str(refusal)))
else:
    print(json.dumps(None))
"""


def _source_with_entry(source: str, table: str, entry: str) -> str:
    """Return *source* with *entry* written first inside the literal its module-level annotated assignment to *table* holds."""
    literals = [
        statement.value
        for statement in ast.parse(source).body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == table
        and statement.value is not None
    ]
    assert len(literals) == 1, (
        f"the source holds {len(literals)} module-level annotated assignments to {table}, not one"
    )
    (literal,) = literals
    lines = source.encode("utf-8").split(b"\n")
    row, column = literal.lineno - 1, literal.col_offset + 1
    lines[row] = lines[row][:column] + entry.encode("utf-8") + lines[row][column:]
    return b"\n".join(lines).decode("utf-8")


@pytest.mark.parametrize(
    ("table", "entry", "offender"),
    [
        pytest.param("__all__", '"Battery", ', "Battery", id="a-name-listed-twice"),
        pytest.param(
            "_SOURCE_NAME", '"Ghost": "TariffPeriod", ', "Ghost", id="an-alias-of-no-exported-name"
        ),
        pytest.param("__all__", '"Ghost", ', "Ghost", id="an-exported-name-with-no-origin-module"),
        pytest.param(
            "_SYMBOL_MODULE", '"Ghost": "battery", ', "Ghost", id="an-origin-module-for-no-exported-name"
        ),
    ],
)
def test_importing_the_package_refuses_tables_that_disagree(
    tmp_path: Path, table: str, entry: str, offender: str
) -> None:
    """Importing a copy of the package whose *table* starts with *entry* raises RuntimeError naming *offender*.

    The copy runs under -O, so an assert could not stand in for the check.  The probe
    loads the copy by its path, not by a search of sys.path, so no installed
    solar_challenge can be imported in its place.  A copy of __init__.py alone suffices,
    because the package imports only importlib and typing at runtime.
    """
    package = tmp_path / "solar_challenge"
    package.mkdir()
    (package / "__init__.py").write_text(
        _source_with_entry(Path(solar_challenge.__file__).read_text(encoding="utf-8"), table, entry),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-I", "-O", "-c", _IMPORT_PROBE, str(package)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, f"the import probe failed:\n{result.stderr}"
    refusal = json.loads(result.stdout)
    assert refusal is not None and repr(offender) in refusal, (
        f"With {entry!r} written first in {table}, importing the package should raise "
        f"RuntimeError naming {offender!r}; it "
        + ("imported" if refusal is None else f"raised RuntimeError: {refusal}")
    )


# ===========================================================================
# The package imports without pvlib
#
# Whether the first access of a name loads pvlib is checked, for each submodule
# the lazy loader maps names to, by
# tests/unit/test_lazy_pvlib_submodules.py::test_the_first_access_of_a_public_name_loads_pvlib_exactly_for_the_listed_submodules
# ===========================================================================


def test_import_is_pvlib_free() -> None:
    """`import solar_challenge` alone leaves pvlib out of sys.modules.

    It runs in a fresh interpreter, since the test process has already imported pvlib.
    """
    code = (
        "import sys, solar_challenge; "
        "sys.exit(0 if 'pvlib' not in sys.modules else 1)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"pvlib was imported by 'import solar_challenge'.\nstderr: {result.stderr}"
    )

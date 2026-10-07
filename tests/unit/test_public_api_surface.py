"""Authoritative surface-lock / freeze guard for the solar_challenge public-API seam.

This is the T4 contract file (PRD docs/prds/domain-library-extraction.md §3.5,
§9 H2/H3/H4, decomposition §10 T4).  It is the single canonical executable
specification that future maintainers must update when the public surface changes.

Concerns:
  H2 surface-lock  — FROZEN_SET, the keys of FROZEN_SURFACE, pins the exact 69 public
                     names (test_all_equals_frozen_set)
  H2 signature     — FROZEN_SURFACE pins each public name's surface form: a class's or
                     routine's signature, an Enum's members, a constant's type
                     (test_every_exported_signature_matches_frozen_surface)
  H2 closure       — FROZEN_CLOSURE pins the surface form of each class outside __all__
                     that the frozen surface names, directly or through another such class
                     (test_every_class_the_frozen_surface_names_matches_frozen_closure)
  H2 members       — FROZEN_MEMBERS pins each pinned class's public members, exported
                     or in FROZEN_CLOSURE: its methods, properties, class constants
                     and declared attributes
                     (test_every_pinned_class_member_matches_frozen_members,
                      test_pinned_classes_inherit_only_from_pinned_classes,
                      test_pinned_classes_declare_the_public_attributes_they_set_on_self)
  H2 kind          — EXPECTED_KIND pins the introspected kind of each name
                     (test_expected_kind_keys_match_frozen_set,
                      test_every_name_resolves_to_expected_kind)
  H3 laziness      — pvlib is absent after bare import; present after touching PVConfig
                     (test_import_is_pvlib_free, test_touching_pvconfig_imports_pvlib)
  H4 collision     — DispatchTariffPeriod / TariffPeriod are distinct objects pointing
                     to different origin classes (test_tariffperiod_collision_resolved)

Relationship to T3 (tests/unit/test_init_lazy_surface.py):
  T3 owns structural checks (count / no-dup / no-CLI / lazy-resolver caching / __dir__ /
  TYPE_CHECKING sync).  T3 defers exact-name pinning to T4.  Bounded overlap in H3 / H4
  is deliberate — this file must stand alone as the complete executable contract.
"""

import abc
import enum
import functools
import inspect
import subprocess
import sys
import types
from collections.abc import Mapping

import solar_challenge
from tests._surface_forms import (
    member_forms,
    signature_closure,
    surface_form,
    undeclared_attributes,
    unset_attributes,
)


# ---------------------------------------------------------------------------
# H2 surface-lock: the exact 69 public names, each with its frozen surface form
#
# The keys mirror PRD §3.1, grouped by origin module.  Each value is the name's
# surface_form (tests/_surface_forms.py): a class's or routine's signature, an
# Enum's members, or a constant's type.  Any add/remove to __all__ must be
# reflected in the keys, and any change to a name's form in its value; the
# tests below fail naming the drifted symbol(s).  Each value stays on one line,
# so the current form a failure prints pastes in verbatim.
# ---------------------------------------------------------------------------
FROZEN_SURFACE: dict[str, str] = {
    # --- finance / bill engine (finance.py) ---
    "bill": "(*, period_days: float, generation_kwh: float, demand_kwh: float, self_consumption_kwh: float, import_kwh: float, import_cost_gbp: float, baseline_import_cost_gbp: float, finance: 'FinanceConfig') -> BillBreakdown",
    "householder_bill": "(summary: 'SummaryStatistics', annual_self_consumption_kwh: float, finance: 'FinanceConfig', simulation_days: int) -> BillBreakdown",
    "solve_cost_recovery_rate": "(scenario: 'ScenarioConfig', finance: 'FinanceConfig', *, simulate: Optional[Callable[['FleetConfig', pd.Timestamp, pd.Timestamp], 'FleetResults']] = None) -> 'CostRecoverySolution'",
    "bill_distribution": "(summaries: Sequence['SummaryStatistics'], finance: 'FinanceConfig', simulation_days: int) -> BillDistribution",
    "BillBreakdown": "(standing_charge_gbp: float, import_cost_gbp: float, own_use_payment_gbp: float, vat_gbp: float, total_outlay_gbp: float, own_use_vat_gbp: float, cbs_amount_due_gbp: float, self_consumption_saving_gbp: float, baseline_bill_gbp: float, saving_vs_baseline_gbp: float, saving_pct: float, self_consumption_fraction: float) -> None",
    "BillDistribution": "(representative: BillBreakdown, per_home_net_bill_gbp: tuple[float, ...], min_gbp: float, mean_gbp: float, median_gbp: float, max_gbp: float) -> None",
    "CostRecoverySolution": "(own_use_rate_pence_per_kwh: float, outlay: 'BillDistribution', representative_outlay_gbp: float, net_surplus_per_home_per_year_gbp: float, saving_vs_baseline_gbp: float, saving_pct: float, feasible: bool, binding: str) -> None",
    "FinanceConfig": "(standing_charge_pence_per_day: float, vat_rate: float = 0.05, retail_baseline_rate_pence_per_kwh: float = 23.0, self_consumption_override: Optional[float] = None, pv_cost_per_kwp_gbp: float = 1000.0, roof_fit_cost_gbp: float = 1000.0, battery_cost_per_kwh_gbp: float = 250.0, inverter_cost_per_kw_gbp: float = 0.0, grant_gbp: float = 250000.0, equity_fraction: float = 0.75, loan_term_years: int = 15, loan_rate: float = 0.07, opex_per_home_per_year_gbp: float = 131.0, asset_life_years: int = 25, own_use_rate_pence_per_kwh: float = 15.0, retained_cash_floor_per_home_per_year_gbp: float = 27.0, grid_services_income_per_kw_per_year_gbp: float = 0.0, grid_services_model: str = 'flat', grid_services_events: Optional['GridServicesEventsConfig'] = None) -> None",
    # --- signature-closure types ---
    "SummaryStatistics": "(total_generation_kwh: float, total_demand_kwh: float, total_self_consumption_kwh: float, total_grid_import_kwh: float, total_grid_export_kwh: float, total_battery_charge_kwh: float, total_battery_discharge_kwh: float, peak_generation_kw: float, peak_demand_kw: float, self_consumption_ratio: float, grid_dependency_ratio: float, export_ratio: float, simulation_days: int, total_import_cost_gbp: float, total_export_revenue_gbp: float, net_cost_gbp: float, strategy_name: str = 'self_consumption', seg_revenue_gbp: float | None = None, total_heat_pump_load_kwh: float | None = None, peak_heat_pump_load_kw: float | None = None, heat_pump_load_ratio: float | None = None, total_grid_charge_cost_gbp: float = 0.0) -> None",
    "ScenarioConfig": "(name: str, period: SimulationPeriod, description: str = '', location: Location | None = None, homes: list[HomeConfig] = <factory>, home: HomeConfig | None = None, output: OutputConfig | None = None, seg_tariff_pence_per_kwh: float | None = None, tariff_config: TariffConfig | None = None, finance: FinanceConfig | None = None) -> None",
    "FleetConfig": "(homes: list[HomeConfig] = <factory>, name: str = '') -> None",
    "FleetResults": "(per_home_results: list[SimulationResults], home_configs: list[HomeConfig]) -> None",
    # --- dispatch (dispatch.py) ---
    "DispatchStrategy": "()",
    "DispatchDecision": "(charge_kw: float, discharge_kw: float, grid_charge_kw: float = 0.0) -> None",
    "GridChargeContext": "(current_rate: float, peak_rate: float, is_cheap_period: bool, target_soc_fraction: float, max_charge_kw: float, round_trip_efficiency: float, charge_efficiency: float) -> None",
    "compute_grid_charge_power_kw": "(ctx: GridChargeContext, *, battery_soc_kwh: float, capacity_kwh: float, pv_charge_power_kw: float, timestep_minutes: float) -> float",
    "SelfConsumptionStrategy": "()",
    "TOUOptimizedStrategy": "(peak_hours: list[tuple[int, int]]) -> None",
    "PeakShavingStrategy": "(import_limit_kw: float) -> None",
    "DispatchTariffPeriod": "PEAK='peak', OFF_PEAK='off_peak'",
    # --- battery (battery.py) ---
    "Battery": "(config: BatteryConfig, initial_soc_kwh: float | None = None, min_soc_fraction: float | None = None, max_soc_fraction: float | None = None, charge_efficiency: float | None = None, discharge_efficiency: float | None = None) -> None",
    "BatteryConfig": "(capacity_kwh: float, max_charge_kw: float = 2.5, max_discharge_kw: float = 2.5, name: str = '', dispatch_strategy: DispatchStrategyConfig | None = None, grid_charging: GridChargeConfig | None = None, min_soc_fraction: float = 0.1, max_soc_fraction: float = 0.9, charge_efficiency: float = 0.975, discharge_efficiency: float = 0.975, efficiency: float | None = None, system_age_years: float = 0.0, calendar_fade_rate_per_year: float = 0.02, cycle_fade_per_equivalent_full_cycle: float = 5e-05, soh_floor: float = 0.5, soh: float | None = None) -> None",
    "compute_soh": "(system_age_years: float, cumulative_throughput_kwh: float, usable_capacity_kwh: float, params: BatteryConfig) -> float",
    # --- flow (flow.py) ---
    "EnergyFlowResult": "(generation: float, demand: float, self_consumption: float, battery_charge: float, battery_discharge: float, grid_export: float, grid_import: float, battery_soc: float, grid_charge: float = 0.0) -> None",
    "simulate_timestep": "(generation_kw: float, demand_kw: float, battery: Battery | None, timestep_minutes: float = 1.0, timestamp: datetime | None = None, strategy: DispatchStrategy | None = None, *, tariff: TariffConfig | None = None) -> EnergyFlowResult",
    "simulate_timestep_tou": "(generation_kw: float, demand_kw: float, battery: Battery | None, timestamp: Timestamp, tariff: TariffConfig, timestep_minutes: float = 1.0) -> EnergyFlowResult",
    "validate_energy_balance": "(result: EnergyFlowResult, tolerance: float = 0.001) -> bool",
    "calculate_self_consumption": "(generation: Series, demand: Series) -> Series",
    "calculate_excess_pv": "(generation: Series, demand: Series) -> Series",
    "calculate_shortfall": "(generation: Series, demand: Series) -> Series",
    # --- tariff (tariff.py) ---
    "TariffConfig": "(periods: tuple[TariffPeriod, ...], name: str = '') -> None",
    "TariffPeriod": "(start_time: str, end_time: str, rate_per_kwh: float, name: str = '') -> None",
    "calculate_bill": "(energy_kwh: Series, tariff: TariffConfig) -> float",
    "FlatRateTariff": "(rate_per_kwh: float, name: str = '') -> TariffConfig",
    # --- seg (seg.py) ---
    "SEGTariff": "(name: str, rate_pence_per_kwh: float) -> None",
    "resolve_seg_tariff": "(name: str) -> SEGTariff",
    "calculate_seg_revenue": "(export_kwh: float, tariff: SEGTariff) -> float",
    "SEG_PRESETS": "dict",
    # --- gridservices (gridservices.py) ---
    "GridServicesRateBand": "(availability_gbp_per_kw_per_event: float, utilisation_gbp_per_mwh: float, provenance: str = '') -> None",
    "GridServicesRateBands": "(low: GridServicesRateBand, central: GridServicesRateBand, high: GridServicesRateBand) -> None",
    "resolve_grid_services_rate_band": "(band: str) -> GridServicesRateBand",
    "EventWindow": "(months: tuple[int, ...], weekdays: tuple[int, ...], hours: tuple[int, ...], events_per_year: int, event_hours: float) -> None",
    "GridServicesEventsConfig": "(band: str = 'central', event_windows: tuple[EventWindow, ...] = (EventWindow(months=(11, 12, 1, 2), weekdays=(0, 1, 2, 3, 4), hours=(16, 17, 18), events_per_year=12, event_hours=3.0),), aggregator_share: float = 0.25, utilisation_factor: float = 0.6, availability_gbp_per_kw_per_event: float | None = None, utilisation_gbp_per_mwh: float | None = None) -> None",
    "GridServicesAtEvents": "(annual_income_gbp: float, per_window_avail_kw: tuple[float, ...], per_window_income_gbp: tuple[float, ...]) -> None",
    "compute_fleet_spare_capacity_kw": "(fleet_results: FleetResults, windows: tuple[EventWindow, ...]) -> tuple[float, ...]",
    "compute_grid_services_at_events": "(fleet_results: FleetResults, cfg: GridServicesEventsConfig) -> GridServicesAtEvents",
    "GRID_SERVICES_RATE_BANDS": "GridServicesRateBands",
    "DEFAULT_EVENT_WINDOWS": "tuple",
    # --- community (community.py) ---
    "CommunityConfig": "(sharing_mode: Literal['p2p', 'community_battery'], community_battery: Optional[BatteryConfig] = None, billing: Optional[CommunityBillingConfig] = None) -> None",
    "CommunityBillingConfig": "(tariff: Optional[TariffConfig] = None, seg_rate_pence_per_kwh: Optional[float] = None) -> None",
    "CommunityResults": "(grid_import: pd.Series, grid_export: pd.Series, battery_charge: pd.Series, battery_discharge: pd.Series, battery_soc: pd.Series, fleet_results: 'FleetResults', sharing_mode: Literal['p2p', 'community_battery'], baseline_net_cost_gbp: Optional[float] = None, community_net_cost_gbp: Optional[float] = None, community_savings_gbp: Optional[float] = None) -> None",
    "simulate_community": "(fleet_results: 'FleetResults', config: CommunityConfig, *, validate_balance: bool = True) -> CommunityResults",
    "validate_community_balance": "(fleet_results: 'FleetResults', community_results: CommunityResults, tolerance: float = 0.001) -> bool",
    # --- pv (pv.py) ---
    "PVConfig": "(capacity_kw: float, azimuth: float = 180.0, tilt: float = 35.0, name: str = '', module_efficiency: float = 0.2, temperature_coefficient: float = -0.004, custom_module_params: dict[str, float] | None = None, inverter_efficiency: float = 0.96, inverter_capacity_kw: float | None = None, custom_inverter_params: dict[str, float] | None = None, system_age_years: float = 0.0, degradation_rate_per_year: float = 0.005) -> None",
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
    # --- load (load.py) ---
    "LoadConfig": "(annual_consumption_kwh: float | None = None, household_occupants: int = 3, name: str = '', use_stochastic: bool = True, seed: int | None = None) -> None",
    "OFGEM_TDCV_BY_OCCUPANTS": "dict",
    "ELEXON_PROFILE_CLASS_1": "list",
    "SEASONAL_FACTORS": "dict",
    # --- location (location.py) ---
    "Location": "(latitude: float, longitude: float, timezone: str = 'Europe/London', altitude: float = 0.0, name: str = '') -> None",
}

FROZEN_SET: frozenset[str] = frozenset(FROZEN_SURFACE)


def test_all_equals_frozen_set() -> None:
    """H2 surface-lock: solar_challenge.__all__ must equal FROZEN_SET exactly.

    Fails on any add/remove to __all__ without updating FROZEN_SET.
    The symmetric-difference message names the exact drifted symbol(s).

    Also asserts len==69 explicitly — a bare set-compare would silently pass
    if __all__ contained a duplicate entry (set collapses duplicates).
    """
    actual = set(solar_challenge.__all__)
    diff = actual.symmetric_difference(FROZEN_SET)
    assert actual == FROZEN_SET, (
        f"__all__ has drifted from FROZEN_SET.  "
        f"Symmetric difference: {sorted(diff)}"
    )
    assert len(solar_challenge.__all__) == len(FROZEN_SET) == 69, (
        f"Length mismatch: __all__ has {len(solar_challenge.__all__)} names, "
        f"FROZEN_SET has {len(FROZEN_SET)} (expected 69 each)"
    )
    # Document the CLI-excluded invariant explicitly
    assert "get_cli_app" not in solar_challenge.__all__, (
        "get_cli_app must remain excluded from __all__ (shipped but unfrozen CLI)"
    )


# ---------------------------------------------------------------------------
# H2 signature: every exported name keeps the surface form FROZEN_SURFACE pins.
# ---------------------------------------------------------------------------


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


def test_every_exported_signature_matches_frozen_surface() -> None:
    """H2 signature-lock: every name in __all__ has the surface form FROZEN_SURFACE pins.

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
# H2 closure: the classes outside __all__ that the frozen surface names, directly
# or through another such class, each with its frozen surface form
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
    "config.DispatchStrategyConfig": "(strategy_type: str, peak_hours: list[tuple[int, int]] | None = None, import_limit_kw: float | None = None) -> None",
    "config.GridChargeConfig": "(target_soc_fraction: float = 0.9) -> None",
    "config.OutputConfig": "(csv_path: str | None = None, include_minute_data: bool = True, include_summary: bool = True, aggregation: str = 'minute') -> None",
    "config.SimulationPeriod": "(start_date: str | Timestamp, end_date: str | Timestamp) -> None",
    "ev.EVConfig": "(charger_type: str, arrival_hour: int, departure_hour: int = 7, required_charge_kwh: float = 35.0, smart_charging_mode: str = 'none', name: str = '') -> None",
    "heat_pump.HeatPumpConfig": "(heat_pump_type: Literal['ASHP', 'GSHP'], thermal_capacity_kw: float, annual_heat_demand_kwh: float = 8000.0, name: str = '') -> None",
    "home.HomeConfig": "(pv_config: PVConfig, load_config: LoadConfig, battery_config: BatteryConfig | None = None, heat_pump_config: HeatPumpConfig | None = None, ev_config: EVConfig | None = None, location: Location = Location(latitude=51.45, longitude=-2.58, timezone='Europe/London', altitude=11.0, name='Bristol, UK'), name: str = '', tariff_config: TariffConfig | None = None, dispatch_strategy: str = 'greedy', seg_tariff: SEGTariff | None = None) -> None",
    "home.SimulationResults": "(generation: Series, demand: Series, self_consumption: Series, battery_charge: Series, battery_discharge: Series, battery_soc: Series, grid_import: Series, grid_export: Series, import_cost: Series, export_revenue: Series, tariff_rate: Series, strategy_name: str = 'self_consumption', heat_pump_load: Series | None = None, grid_charge_cost: Series | None = None) -> None",
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
    """H2 closure-lock: each class outside __all__ that the frozen surface names has the surface form FROZEN_CLOSURE pins.

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
# H2 members: each pinned class's public members, with their frozen forms
#
# A pinned class is an exported class or a FROZEN_CLOSURE class.  Keys are the
# pinned classes' paths below solar_challenge, then member names: exported
# classes first, in __all__ order, then closure classes in path order, and
# members in class-body order, the order a failure lists drifted members in.
# Each value is the member's form as member_forms spells it
# (tests/_surface_forms.py).  A class with no public member has no entry.  Each
# value stays on one line, so the current form a failure prints pastes in
# verbatim.
# ---------------------------------------------------------------------------
FROZEN_MEMBERS: dict[str, dict[str, str]] = {
    # --- signature-closure types ---
    "ScenarioConfig": {
        "is_fleet": "property (self) -> bool",
        "get_location": "(self) -> Location",
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
        "min_soc_fraction": "attribute float",
        "max_soc_fraction": "attribute float",
        "charge_efficiency": "attribute float",
        "discharge_efficiency": "attribute float",
        "soh": "property (self) -> float",
        "effective_capacity_kwh": "property (self) -> float",
        "soc_kwh": "property (self) -> float",
        "soc_fraction": "property (self) -> float",
        "min_soc_kwh": "property (self) -> float",
        "max_soc_kwh": "property (self) -> float",
        "usable_capacity_kwh": "property (self) -> float",
        "available_charge_capacity_kwh": "property (self) -> float",
        "available_discharge_capacity_kwh": "property (self) -> float",
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
        "get_rate": "(self, timestamp: Timestamp) -> float",
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
    "ev.EVConfig": {
        "get_charger_power_kw": "(self) -> float",
        "get_available_charging_hours": "(self) -> float",
    },
    "heat_pump.HeatPumpConfig": {
        "default_ashp": "classmethod (cls) -> HeatPumpConfig",
        "default_gshp": "classmethod (cls) -> HeatPumpConfig",
    },
    "home.SimulationResults": {
        "per_minute_amounts": "(self) -> DataFrame",
        "total_amounts": "(self) -> dict[str, float]",
        "to_dataframe": "(self) -> DataFrame",
        "from_dataframe": "classmethod (cls, frame: DataFrame, *, strategy_name: str) -> SimulationResults",
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
    """H2 member-lock: every pinned class's public members have the forms FROZEN_MEMBERS pins.

    Fails once, naming each added, changed or removed member with its frozen and current
    forms, in pinned-class and class-body order, removed members last.  An added member's
    current form is printed ready to paste; a removed member's current form reads
    (removed).
    """
    frozen = _forms_by_member_path(FROZEN_MEMBERS)
    current = _forms_by_member_path(
        {path: member_forms(cls) for path, cls in _pinned_classes().items()}
    )
    drifted = _drifted(frozen, current, absent="(removed)")
    assert not drifted, _drift_message("FROZEN_MEMBERS", frozen, drifted)


_STDLIB_BASES: tuple[type, ...] = (object, abc.ABC, enum.Enum)


def test_pinned_classes_inherit_only_from_pinned_classes() -> None:
    """H2 member-lock guard: a pinned class's bases are pinned classes or _STDLIB_BASES.

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


def test_pinned_classes_declare_the_public_attributes_they_set_on_self() -> None:
    """H2 member-lock guard: a pinned class declares in a class body each public attribute it sets on self, and sets each one its body only declares.

    member_forms reads class bodies, so FROZEN_MEMBERS pins an instance attribute only
    once its class body declares it, e.g. `cache_dir: Path`; and a declaration that
    nothing sets would pin a name that instances lack.
    """
    classes = _pinned_classes()
    undeclared = [
        f"{path}.{attribute}"
        for path, cls in classes.items()
        for attribute in sorted(undeclared_attributes(cls))
    ]
    unset = [
        f"{path}.{attribute}"
        for path, cls in classes.items()
        for attribute in sorted(unset_attributes(cls))
    ]
    assert not undeclared and not unset, (
        f"Public attributes set on self that no class body declares: {undeclared}. "
        f"Attributes a class body declares that nothing sets on self: {unset}. "
        "member_forms reads class bodies, so FROZEN_MEMBERS cannot pin an attribute "
        "that is only set on self. Declare each such attribute in its class body, e.g. "
        "`cache_dir: Path`, then add its FROZEN_MEMBERS entry and its 'Unreleased on "
        "main' line in docs/domain-library-consumption.md, or make it private; and drop "
        "each declaration that nothing sets."
    )


# ---------------------------------------------------------------------------
# H2 kind: targeted gotcha-guard for names whose kind would be WRONG if
# inferred from naming convention alone.
#
# The full surface is pinned by FROZEN_SURFACE above.  This table supplements
# it with explicit kind checks only for the non-obvious entries:
#   • FlatRateTariff  — CamelCase looks like a class; it is a factory function
#   • GRID_SERVICES_RATE_BANDS — UPPER_CASE looks like a plain constant; it is
#     a frozen-dataclass instance (still "constant" in our taxonomy, but the
#     distinction is worth pinning)
#   • DispatchTariffPeriod — Enum alias; verifies it resolves to a class, not
#     to a string/sentinel from a botched re-export
#
# taxonomy (for reference):
#   class    → inspect.isclass  (covers dataclasses, Enums, ABCs)
#   function → inspect.isroutine (covers all def functions / factory callables)
#   constant → neither           (dicts, tuples, lists, frozen-dataclass instances)
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


def test_every_name_resolves_to_expected_kind() -> None:
    """H2: all public names resolve via the PEP-562 lazy loader; gotcha kinds are correct.

    Iterates every name in FROZEN_SET — exercises solar_challenge.__getattr__
    and must not raise AttributeError for any name.

    For the small subset named in EXPECTED_KIND (the gotcha entries where naming
    convention would mislead), additionally asserts the introspected kind is correct.
    """
    for name in sorted(FROZEN_SET):
        obj = getattr(solar_challenge, name)  # triggers lazy loader; must not raise
        if name in EXPECTED_KIND:
            actual_kind = _kind(obj)
            assert actual_kind == EXPECTED_KIND[name], (
                f"solar_challenge.{name}: expected kind={EXPECTED_KIND[name]!r}, "
                f"got kind={actual_kind!r} (type={type(obj).__name__})"
            )


# ---------------------------------------------------------------------------
# H3 laziness: pvlib must NOT be imported by a bare `import solar_challenge`;
# it MUST be present after touching a pv-module symbol.
#
# Both sub-tests use a CLEAN interpreter via subprocess to avoid contamination
# from pvlib being already loaded by the test process.
# ---------------------------------------------------------------------------


def test_import_is_pvlib_free() -> None:
    """`import solar_challenge` alone must NOT pull pvlib into sys.modules (H3 clean direction)."""
    code = (
        "import sys, solar_challenge; "
        "sys.exit(0 if 'pvlib' not in sys.modules else 1)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"pvlib was imported by 'import solar_challenge'.\nstderr: {result.stderr}"
    )


def test_touching_pvconfig_imports_pvlib() -> None:
    """`solar_challenge.PVConfig` DOES pull pvlib — lazy proven in both directions (H3 load direction)."""
    code = (
        "import sys, solar_challenge; "
        "solar_challenge.PVConfig; "
        "sys.exit(0 if 'pvlib' in sys.modules else 1)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"pvlib was NOT imported after touching solar_challenge.PVConfig.\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# H4 collision: DispatchTariffPeriod (dispatch Enum) and TariffPeriod
# (tariff dataclass) are distinct objects with distinct origin classes.
# ---------------------------------------------------------------------------


def test_tariffperiod_collision_resolved() -> None:
    """H4: DispatchTariffPeriod and TariffPeriod are distinct objects (collision-renamed correctly).

    dispatch.TariffPeriod (Enum) is exposed as DispatchTariffPeriod.
    tariff.TariffPeriod (dataclass) is exposed as TariffPeriod.
    They must be distinct — otherwise one silently shadows the other.
    """
    import solar_challenge.dispatch as _dispatch
    import solar_challenge.tariff as _tariff

    assert solar_challenge.DispatchTariffPeriod is _dispatch.TariffPeriod, (
        "solar_challenge.DispatchTariffPeriod must be dispatch.TariffPeriod"
    )
    assert solar_challenge.TariffPeriod is _tariff.TariffPeriod, (
        "solar_challenge.TariffPeriod must be tariff.TariffPeriod"
    )
    assert solar_challenge.DispatchTariffPeriod is not solar_challenge.TariffPeriod, (
        "DispatchTariffPeriod and TariffPeriod must be distinct objects"
    )

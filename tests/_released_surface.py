# SPDX-License-Identifier: AGPL-3.0-or-later
"""The frozen tables of tests/unit/test_public_api_surface.py as the last release shipped them.

Each RELEASED_X is FROZEN_X at that release's commit, comments and order included, each
value on one line, and RELEASED_VERSION is the version of the release they are a snapshot
of. The release convention (docs/domain-library-consumption.md, "Tag / release
convention") replaces them.
"""

RELEASED_VERSION = "0.6.0"

RELEASED_SURFACE: dict[str, str] = {
    # --- finance / bill engine (finance.py) ---
    "bill": "(*, period_days: float, generation_kwh: float, demand_kwh: float, self_consumption_kwh: float, import_kwh: float, import_cost_gbp: float, baseline_import_cost_gbp: float, finance: FinanceConfig) -> BillBreakdown",
    "householder_bill": "(summary: SummaryStatistics, window_self_consumption_kwh: float, finance: FinanceConfig) -> BillBreakdown",
    "bill_distribution": "(summaries: Sequence[SummaryStatistics], finance: FinanceConfig) -> BillDistribution",
    "BillBreakdown": "dataclass[eq, frozen, match_args] (standing_charge_gbp: float, import_cost_gbp: float, own_use_payment_gbp: float, vat_gbp: float, total_outlay_gbp: float, own_use_vat_gbp: float, cbs_amount_due_gbp: float, self_consumption_saving_gbp: float, baseline_bill_gbp: float, saving_vs_baseline_gbp: float, saving_pct: float, self_consumption_fraction: float) -> None",
    "BillDistribution": "dataclass[eq, frozen, match_args] (representative: BillBreakdown, per_home_total_outlay_gbp: tuple[float, ...], min_gbp: float, mean_gbp: float, median_gbp: float, max_gbp: float, annualised_from: SimulationWindow, grid_charge_forecasts: tuple[Literal['pv_blind', 'trailing_14_days', 'perfect_foresight'], ...] = ()) -> None",
    "CostRecoverySolution": "dataclass[eq, frozen, match_args] (own_use_rate_pence_per_kwh: float, outlay: BillDistribution, representative_outlay_gbp: float, net_surplus_per_home_per_year_gbp: float, saving_vs_baseline_gbp: float, saving_pct: float, feasible: bool, binding: str) -> None",
    "FinanceConfig": "dataclass[eq, frozen, match_args] (standing_charge_pence_per_day: float, vat_rate: float = 0.05, retail_baseline_rate_pence_per_kwh: float = 23.0, self_consumption_override: float | None = None, pv_cost_per_kwp_gbp: float = 1000.0, roof_fit_cost_gbp: float = 1000.0, battery_cost_per_kwh_gbp: float = 250.0, inverter_cost_per_kw_gbp: float = 0.0, grant_gbp: float = 250000.0, equity_fraction: float = 0.75, loan_term_years: int = 15, loan_rate: float = 0.07, opex_per_home_per_year_gbp: float = 131.0, asset_life_years: int = 25, own_use_rate_pence_per_kwh: float = 15.0, retained_cash_floor_per_home_per_year_gbp: float = 27.0, grid_services_model: NoGridServices | FlatGridServices | GridServicesEventsConfig = NoGridServices()) -> None",
    # --- cost-recovery solve (projection.py) ---
    "solve_cost_recovery_rate": "(scenario: ScenarioConfig, finance: FinanceConfig, *, simulate: Callable[[FleetConfig, Timestamp, Timestamp], FleetResults]) -> CostRecoverySolution",
    # --- signature-closure types ---
    "SummaryStatistics": "dataclass[eq, frozen, match_args] (total_generation_kwh: float, total_demand_kwh: float, total_self_consumption_kwh: float, total_grid_import_kwh: float, total_grid_export_kwh: float, total_battery_charge_kwh: float, total_battery_discharge_kwh: float, peak_generation_kw: float, peak_demand_kw: float, self_consumption_ratio: float, grid_dependency_ratio: float, export_ratio: float, window: SimulationWindow, total_import_cost_gbp: float, total_export_revenue_gbp: float, net_cost_gbp: float, strategy_name: str = 'self_consumption', total_grid_charge_cost_gbp: float = 0.0, total_grid_charge_kwh: float = 0.0, pricing: RunPricing | None = None, grid_charge_forecast: Literal['pv_blind', 'trailing_14_days', 'perfect_foresight'] | None = None, *, load_energy_kwh: Mapping[LoadKind, float]) -> None",
    "ScenarioConfig": "dataclass[eq, frozen, match_args] (name: str, period: SimulationWindow, description: str = '', location: Location | None = None, homes: tuple[HomeConfig, ...] = (), home: HomeConfig | None = None, seg_tariff_pence_per_kwh: float | None = None, finance: FinanceConfig | None = None, flex_band: GridServicesBand | None = None) -> None",
    "FleetConfig": "dataclass[eq, frozen, match_args] (homes: tuple[HomeConfig, ...] = (), name: str = '') -> None",
    "FleetResults": "dataclass[eq, frozen, match_args] (per_home_results: tuple[SimulationResults, ...], home_configs: tuple[HomeConfig, ...]) -> None",
    # --- fleet execution (fleet.py) ---
    "FleetRunner": "dataclass[eq, frozen, match_args] (weather: WeatherProvider, home_simulator: HomeSimulator, parallel: bool = True, max_workers: int | None = None) -> None",
    "FleetSimulator": "(*args, **kwargs)",
    "HomeSimulator": "(*args, **kwargs)",
    "FleetSimulate": "_CallableGenericAlias",
    "HomesDone": "_CallableGenericAlias",
    # --- dispatch (dispatch.py) ---
    "DispatchStrategy": "()",
    "DispatchDecision": "dataclass[eq, frozen, match_args] (charge_kw: float, discharge_kw: float, grid_charge_kw: float = 0.0) -> None",
    "GridChargeContext": "dataclass[eq, frozen, match_args] (current_rate: float, peak_rate: float, is_cheap_period: bool, target_soc_kwh: float, max_charge_kw: float, round_trip_efficiency: float, charge_efficiency: float, useful_charge_ceiling_kwh: float | None = None) -> None",
    "compute_grid_charge_power_kw": "(ctx: GridChargeContext, *, battery_soc_kwh: float, pv_charge_power_kw: float, timestep_minutes: float) -> float",
    "SelfConsumptionStrategy": "()",
    "TOUOptimizedStrategy": "(peak_hours: list[tuple[int, int]] | None = None, *, tariff: TariffConfig | None = None) -> None",
    "PeakShavingStrategy": "(import_limit_kw: float) -> None",
    "DispatchTariffPeriod": "PEAK='peak', OFF_PEAK='off_peak'",
    # --- battery (battery.py) ---
    "Battery": "(config: BatteryConfig, initial_soc_kwh: float | None = None, min_soc_fraction: float | None = None, max_soc_fraction: float | None = None, charge_efficiency: float | None = None, discharge_efficiency: float | None = None) -> None",
    "BatteryConfig": "dataclass[eq, frozen, match_args] (capacity_kwh: float, max_charge_kw: float = 2.5, max_discharge_kw: float = 2.5, name: str = '', dispatch_strategy: SelfConsumptionStrategyConfig | TOUOptimizedStrategyConfig | PeakShavingStrategyConfig = SelfConsumptionStrategyConfig(strategy_type='self_consumption'), grid_charging: GridChargeConfig | None = None, min_soc_fraction: float = 0.1, max_soc_fraction: float = 0.9, charge_efficiency: float = 0.975, discharge_efficiency: float = 0.975, system_age_years: float = 0.0, calendar_fade_rate_per_year: float = 0.02, cycle_fade_per_equivalent_full_cycle: float = 5e-05, soh_floor: float = 0.5, soh: float | None = None) -> None",
    "compute_soh": "(system_age_years: float, cumulative_throughput_kwh: float, usable_capacity_kwh: float, params: BatteryConfig) -> float",
    # --- flow (flow.py) ---
    "EnergyFlowResult": "dataclass[eq, frozen, match_args] (generation: float, demand: float, self_consumption: float, battery_charge: float, battery_discharge: float, grid_export: float, grid_import: float, battery_soc: float, grid_charge: float = 0.0) -> None",
    "simulate_timestep": "(generation_kw: float, demand_kw: float, battery: Battery | None, timestep_minutes: float, timestamp: datetime | None = None, strategy: DispatchStrategy | None = None, *, tariff: TariffConfig | None = None, useful_charge_ceiling_kwh: float | None = None) -> EnergyFlowResult",
    "validate_energy_balance": "(result: EnergyFlowResult, tolerance: float = 0.001) -> bool",
    "calculate_self_consumption": "(generation: Series, demand: Series) -> Series",
    "calculate_excess_pv": "(generation: Series, demand: Series) -> Series",
    "calculate_shortfall": "(generation: Series, demand: Series) -> Series",
    # --- tariff (tariff.py) ---
    "TariffConfig": "dataclass[eq, frozen, match_args] (periods: tuple[TariffPeriod, ...], name: str = '') -> None",
    "TariffPeriod": "dataclass[eq, frozen, match_args] (start_time: str, end_time: str, rate_per_kwh: float, name: str = '') -> None",
    "calculate_bill": "(energy_kwh: Series, tariff: TariffConfig) -> float",
    "FlatRateTariff": "(rate_per_kwh: float, name: str = '') -> TariffConfig",
    # --- seg (seg.py) ---
    "SEGTariff": "dataclass[eq, frozen, match_args] (name: str, rate_pence_per_kwh: float) -> None",
    "resolve_seg_tariff": "(name: str) -> SEGTariff",
    "calculate_seg_revenue": "(export_kwh: float, tariff: SEGTariff) -> float",
    "SEG_PRESETS": "dict {'Octopus': SEGTariff, 'British Gas': SEGTariff, 'EDF': SEGTariff, 'E.ON': SEGTariff, 'Scottish Power': SEGTariff, 'OVO': SEGTariff}",
    # --- gridservices (gridservices.py) ---
    "GridServicesRateBand": "dataclass[eq, frozen, match_args] (availability_gbp_per_kw_per_event: float, utilisation_gbp_per_mwh: float, provenance: str = '', flat_gbp_per_kw_per_year: float = 0.0) -> None",
    "GridServicesRateBands": "dataclass[eq, frozen, match_args] (low: GridServicesRateBand, central: GridServicesRateBand, high: GridServicesRateBand) -> None",
    "resolve_grid_services_rate_band": "(band: GridServicesBand) -> GridServicesRateBand",
    "EventWindow": "dataclass[eq, frozen, match_args] (months: tuple[int, ...], weekdays: tuple[int, ...], hours: tuple[int, ...], events_per_year: int, event_hours: float) -> None",
    "GridServicesEventsConfig": "dataclass[eq, frozen, match_args] (band: GridServicesBand = <GridServicesBand.CENTRAL: 'central'>, event_windows: tuple[EventWindow, ...] = (EventWindow(months=(11, 12, 1, 2), weekdays=(0, 1, 2, 3, 4), hours=(16, 17, 18), events_per_year=12, event_hours=3.0),), aggregator_share: float = 0.25, utilisation_factor: float = 0.6, availability_gbp_per_kw_per_event: float | None = None, utilisation_gbp_per_mwh: float | None = None, delivery_baseline: str = 'operational') -> None",
    "GridServicesAtEvents": "dataclass[eq, frozen, match_args] (annual_income_gbp: float, per_window_avail_kw: tuple[float, ...], per_window_income_gbp: tuple[float, ...], per_window_avail_p50_kw: tuple[float, ...], per_window_avail_p90_kw: tuple[float, ...], per_window_displaced_self_use_kwh_per_event: tuple[float, ...], per_window_displaced_import_gbp_per_year: tuple[float, ...]) -> None",
    "compute_fleet_spare_capacity_kw": "(fleet_results: FleetResults, windows: tuple[EventWindow, ...], delivery_baseline: str = 'operational') -> tuple[float, ...]",
    "compute_grid_services_at_events": "(fleet_results: FleetResults, cfg: GridServicesEventsConfig) -> GridServicesAtEvents",
    "GRID_SERVICES_RATE_BANDS": "GridServicesRateBands",
    "GridServicesBand": "LOW='low', CENTRAL='central', HIGH='high'",
    "NoGridServices": "dataclass[eq, frozen] () -> None",
    "FlatGridServices": "dataclass[eq, frozen, match_args] (income_per_kw_per_year_gbp: float) -> None",
    "DEFAULT_EVENT_WINDOWS": "tuple [EventWindow]",
    # --- community (community.py) ---
    "CommunityConfig": "dataclass[eq, frozen] (*, community_battery: BatteryConfig | None = None, billing: CommunityBillingConfig | None = None) -> None",
    "CommunityBillingConfig": "dataclass[eq, frozen, match_args] (tariff: TariffConfig | None = None, seg_rate_pence_per_kwh: float | None = None) -> None",
    "CommunityResults": "dataclass[eq, frozen, match_args] (grid_import: Series, grid_export: Series, battery_charge: Series, battery_discharge: Series, battery_soc: Series, fleet_results: FleetResults, sharing_mode: Literal['p2p', 'community_battery'], baseline_net_cost_gbp: float | None = None, community_net_cost_gbp: float | None = None, community_savings_gbp: float | None = None) -> None",
    "simulate_community": "(fleet_results: FleetResults, config: CommunityConfig, *, validate_balance: bool = True) -> CommunityResults",
    "validate_community_balance": "(fleet_results: FleetResults, community_results: CommunityResults, tolerance: float = 0.001) -> bool",
    # --- pv (pv.py) ---
    "PVConfig": "dataclass[eq, frozen, match_args] (capacity_kw: float, azimuth: float = 180.0, tilt: float = 35.0, name: str = '', module_efficiency: float | None = None, temperature_coefficient: float | None = None, custom_module_params: dict[str, float] | None = None, inverter_efficiency: float = 0.96, inverter_capacity_kw: float | None = None, custom_inverter_params: dict[str, float] | None = None, system_age_years: float = 0.0, degradation_rate_per_year: float = 0.005, system_losses: float = 0.14075660688264469) -> None",
    "simulate_pv_output": "(config: PVConfig, location: Location, weather_data: DataFrame) -> Series",
    "create_model_chain": "(config: PVConfig, location: Location) -> ModelChain",
    "create_pv_system": "(config: PVConfig) -> PVSystem",
    "calculate_degradation_factor": "(system_age_years: float, degradation_rate_per_year: float = 0.005) -> float",
    "interpolate_to_minute_resolution": "(hourly_power: Series) -> Series",
    # --- weather (weather.py) ---
    "WeatherCache": "(cache_dir: Path | None = None) -> None",
    "WeatherProvider": "(*args, **kwargs)",
    "PvgisTmy": "dataclass[eq, frozen, match_args] (cache: WeatherCache | None) -> None",
    "PrefetchedWeather": "dataclass[frozen, match_args] (frames: Mapping[Location, DataFrame]) -> None",
    # --- load (load.py) ---
    "LoadConfig": "dataclass[eq, frozen, match_args] (annual_consumption_kwh: float | None = None, household_occupants: int = 3, name: str = '', use_stochastic: bool = True, seed: int | None = None) -> None",
    "OFGEM_TDCV_BY_OCCUPANTS": "dict {1: float, 2: float, 3: float, 4: float, 5: float}",
    "ELEXON_PROFILE_CLASS_1": "list [float × 48]",
    "SEASONAL_FACTORS": "dict {1: float, 2: float, 3: float, 4: float, 5: float, 6: float, 7: float, 8: float, 9: float, 10: float, 11: float, 12: float}",
    # --- location (location.py) ---
    "Location": "dataclass[eq, frozen, match_args] (latitude: float, longitude: float, timezone: str = 'Europe/London', altitude: float = 0.0, name: str = '') -> None",
    # --- errors (errors.py) ---
    "ConfigurationError": "(*args: object) -> None",
}


RELEASED_CLOSURE: dict[str, str] = {
    "battery.SocEnvelope": "dataclass[eq, frozen, match_args] (effective_capacity_kwh: float, min_soc_kwh: float, max_soc_kwh: float) -> None",
    "demand.LoadKind": "HOUSEHOLD='household', HEAT_PUMP='heat_pump', EV='ev'",
    "dispatch.GridChargeConfig": "dataclass[eq, frozen, match_args] (target_soc_fraction: float = 0.9, forecast: Literal['pv_blind', 'trailing_14_days', 'perfect_foresight'] = 'pv_blind') -> None",
    "dispatch.PeakShavingStrategyConfig": "dataclass[eq, frozen, match_args] (import_limit_kw: float) -> None",
    "dispatch.SelfConsumptionStrategyConfig": "dataclass[eq, frozen] () -> None",
    "dispatch.TOUOptimizedStrategyConfig": "dataclass[eq, frozen, match_args] (peak_hours: tuple[tuple[int, int], ...] | None = None) -> None",
    "ev.EVChargerType": "SLOW='3.6kW', FAST='7kW', RAPID='22kW'",
    "ev.EVConfig": "dataclass[eq, frozen, match_args] (charger_type: EVChargerType, arrival_hour: int = 18, departure_hour: int = 7, required_charge_kwh: float = 35.0, smart_charging_mode: SmartChargingMode = <SmartChargingMode.NONE: 'none'>, name: str = '') -> None",
    "ev.SmartChargingMode": "NONE='none', SOLAR='solar', OFF_PEAK='off_peak'",
    "heat_pump.HeatPumpConfig": "dataclass[eq, frozen, match_args] (heat_pump_type: Literal['ASHP', 'GSHP'], thermal_capacity_kw: float = 8.0, annual_heat_demand_kwh: float = 8000.0, name: str = '') -> None",
    "home.HomeConfig": "dataclass[eq, frozen, match_args] (pv_config: PVConfig, load_config: LoadConfig, battery_config: BatteryConfig | None = None, heat_pump_config: HeatPumpConfig | None = None, ev_config: EVConfig | None = None, location: Location = Location(latitude=51.45, longitude=-2.58, timezone='Europe/London', altitude=11.0, name='Bristol, UK'), name: str = '', tariff_config: TariffConfig | None = None, seg_tariff: SEGTariff | None = None) -> None",
    "home.RunPricing": "dataclass[eq, frozen, match_args] (import_tariff_mean_rate_gbp_per_kwh: float | None, seg_rate_pence_per_kwh: float | None) -> None",
    "home.SimulationResults": "dataclass[eq, frozen, match_args] (generation: Series, demand: Series, self_consumption: Series, battery_charge: Series, battery_discharge: Series, battery_soc: Series, grid_import: Series, grid_export: Series, import_cost: Series, export_revenue: Series, tariff_rate: Series, strategy_name: str = 'self_consumption', grid_charge_cost: Series | None = None, grid_charge: Series | None = None, pricing: RunPricing | None = None, grid_charge_forecast: Literal['pv_blind', 'trailing_14_days', 'perfect_foresight'] | None = None, additional_loads: Mapping[LoadKind, Series] = <factory>) -> None",
    "timebase.LocalDay": "dataclass[frozen, match_args] (date: date, rows: DatetimeIndex) -> None",
    "timebase.SimulationWindow": "dataclass[eq, frozen, match_args] (first_day: date, last_day: date, cadence: timedelta, timezone: str | None = None) -> None",
}


RELEASED_MEMBERS: dict[str, dict[str, str]] = {
    # --- signature-closure types ---
    "SummaryStatistics": {
        "simulation_days": "property (self) -> int",
        "total_pv_charge_kwh": "property (self) -> float",
        "total_direct_self_consumption_kwh": "property (self) -> float",
        "total_grid_to_demand_kwh": "property (self) -> float",
        "load_share": "(self, kind: LoadKind) -> float",
    },
    "ScenarioConfig": {
        "is_fleet": "property (self) -> bool",
        "get_location": "(self) -> Location",
        "simulated_homes": "(self) -> tuple[HomeConfig, ...]",
        "map_homes": "(self, transform: Callable[[HomeConfig], HomeConfig]) -> ScenarioConfig",
        "window": "(self) -> SimulationWindow",
        "with_window": "(self, *, first_day: date | None = None, last_day: date | None = None) -> ScenarioConfig",
        "simulation_bounds": "(self) -> tuple[Timestamp, Timestamp]",
    },
    "FleetConfig": {
        "create_uniform": "classmethod (cls, n_homes: int, pv_config: PVConfig, load_config: LoadConfig, battery_config: BatteryConfig | None = None, location: Location = Location(latitude=51.45, longitude=-2.58, timezone='Europe/London', altitude=11.0, name='Bristol, UK'), name: str = '', *, seed: int | None = None) -> FleetConfig",
        "create_heterogeneous": "classmethod (cls, pv_capacities_kw: list[float], battery_capacities_kwh: list[float | None], annual_consumptions_kwh: list[float], location: Location = Location(latitude=51.45, longitude=-2.58, timezone='Europe/London', altitude=11.0, name='Bristol, UK'), name: str = '', *, seed: int | None = None) -> FleetConfig",
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
    # --- fleet execution (fleet.py) ---
    "FleetRunner": {
        "simulate": "(self, fleet: FleetConfig, start_date: Timestamp, end_date: Timestamp, *, progress: Callable[[int, int], None] | None = None) -> FleetResults",
        "simulate_each": "(self, fleets: Sequence[FleetConfig], start_date: Timestamp, end_date: Timestamp, *, progress: Callable[[int, int], None] | None = None) -> Iterator[tuple[int, FleetResults]]",
        "simulate_home": "(self, home: HomeConfig, start_date: Timestamp, end_date: Timestamp) -> SimulationResults",
    },
    "FleetSimulator": {
        "simulate": "(self, fleet: FleetConfig, start_date: Timestamp, end_date: Timestamp, *, progress: Callable[[int, int], None] | None = None) -> FleetResults",
        "simulate_each": "(self, fleets: Sequence[FleetConfig], start_date: Timestamp, end_date: Timestamp, *, progress: Callable[[int, int], None] | None = None) -> Iterator[tuple[int, FleetResults]]",
        "simulate_home": "(self, home: HomeConfig, start_date: Timestamp, end_date: Timestamp) -> SimulationResults",
    },
    # --- dispatch (dispatch.py) ---
    "DispatchStrategy": {
        "name": "abstract property (self) -> str",
        "charges_from_the_grid": "property (self) -> bool",
        "decide_action": "abstract (self, timestamp: datetime, generation_kw: float, demand_kw: float, battery_soc_kwh: float, battery_capacity_kwh: float, timestep_minutes: float, *, grid_charge_ctx: GridChargeContext | None = None) -> DispatchDecision",
    },
    "SelfConsumptionStrategy": {
        "name": "property (self) -> str",
        "charges_from_the_grid": "property (self) -> bool",
        "decide_action": "(self, timestamp: datetime, generation_kw: float, demand_kw: float, battery_soc_kwh: float, battery_capacity_kwh: float, timestep_minutes: float, *, grid_charge_ctx: GridChargeContext | None = None) -> DispatchDecision",
    },
    "TOUOptimizedStrategy": {
        "name": "property (self) -> str",
        "charges_from_the_grid": "property (self) -> bool",
        "decide_action": "(self, timestamp: datetime, generation_kw: float, demand_kw: float, battery_soc_kwh: float, battery_capacity_kwh: float, timestep_minutes: float, *, grid_charge_ctx: GridChargeContext | None = None) -> DispatchDecision",
    },
    "PeakShavingStrategy": {
        "name": "property (self) -> str",
        "charges_from_the_grid": "property (self) -> bool",
        "decide_action": "(self, timestamp: datetime, generation_kw: float, demand_kw: float, battery_soc_kwh: float, battery_capacity_kwh: float, timestep_minutes: float, *, grid_charge_ctx: GridChargeContext | None = None) -> DispatchDecision",
    },
    # --- battery (battery.py) ---
    "Battery": {
        "config": "property[settable] (self) -> BatteryConfig",
        "min_soc_fraction": "property[settable] (self) -> float",
        "max_soc_fraction": "property[settable] (self) -> float",
        "charge_efficiency": "property[settable] (self) -> float",
        "discharge_efficiency": "property[settable] (self) -> float",
        "soh": "property (self) -> float",
        "soc_envelope": "property (self) -> SocEnvelope",
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
        "resolved_soh": "property (self) -> float",
        "soc_envelope": "(self) -> SocEnvelope",
        "with_round_trip": "(self, round_trip_efficiency: float) -> BatteryConfig",
        "default_5kwh": "classmethod (cls) -> BatteryConfig",
    },
    # --- tariff (tariff.py) ---
    "TariffConfig": {
        "peak_rate": "cached_property (self) -> float",
        "cheap_minutes_of_day": "cached_property (self) -> frozenset[int]",
        "get_rate": "(self, timestamp: datetime) -> float",
        "rates_for": "(self, index: DatetimeIndex) -> ndarray",
        "is_cheap_at": "(self, timestamp: datetime) -> bool",
        "flat_rate": "classmethod (cls, rate_per_kwh: float, name: str = '') -> TariffConfig",
        "economy_7": "classmethod (cls, off_peak_rate: float = 0.13, peak_rate: float = 0.35, off_peak_start: str = '00:30', off_peak_end: str = '07:30') -> TariffConfig",
        "economy_10": "classmethod (cls, off_peak_rate: float = 0.13, peak_rate: float = 0.35, night_start: str = '00:00', night_end: str = '05:00', afternoon_start: str = '13:00', afternoon_end: str = '16:00', evening_start: str = '20:00', evening_end: str = '22:00') -> TariffConfig",
    },
    "TariffPeriod": {
        "get_start_time": "(self) -> time",
        "get_end_time": "(self) -> time",
        "matches_time": "(self, timestamp: datetime) -> bool",
    },
    # --- gridservices (gridservices.py) ---
    "GridServicesRateBands": {
        "resolve": "(self, band: GridServicesBand) -> GridServicesRateBand",
    },
    "EventWindow": {
        "mask": "(self, index: DatetimeIndex) -> Series",
    },
    "GridServicesEventsConfig": {
        "annual_income_gbp": "(self, fleet_results: FleetResults) -> float",
    },
    "GridServicesBand": {
        "parse": "classmethod (cls, value: object, *, what: str) -> GridServicesBand",
    },
    "NoGridServices": {
        "annual_income_gbp": "(self, fleet_results: FleetResults) -> float",
    },
    "FlatGridServices": {
        "annual_income_gbp": "(self, fleet_results: FleetResults) -> float",
    },
    # --- community (community.py) ---
    "CommunityConfig": {
        "sharing_mode": "property (self) -> Literal['p2p', 'community_battery']",
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
    # --- errors (errors.py) ---
    "ConfigurationError": {
        "must_be": "classmethod (cls, field: str, requirement: str, *, got: object) -> typing.Self",
    },
    # --- classes outside __all__ (FROZEN_CLOSURE) ---
    "battery.SocEnvelope": {
        "target_kwh": "(self, fraction: float) -> float",
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
    "demand.LoadKind": {
        "column": "property (self) -> str",
        "energy_column": "property (self) -> str",
        "label": "property (self) -> str",
        "parse": "classmethod (cls, value: object) -> LoadKind",
    },
    "ev.EVChargerType": {
        "parse": "classmethod (cls, value: object, *, field: str) -> EVChargerType",
        "power_kw": "property (self) -> float",
    },
    "ev.EVConfig": {
        "get_charger_power_kw": "(self) -> float",
        "get_available_charging_hours": "(self) -> float",
    },
    "ev.SmartChargingMode": {
        "parse": "classmethod (cls, value: object, *, field: str) -> SmartChargingMode",
    },
    "heat_pump.HeatPumpConfig": {
        "default_ashp": "classmethod (cls) -> HeatPumpConfig",
        "default_gshp": "classmethod (cls) -> HeatPumpConfig",
    },
    "home.SimulationResults": {
        "loads": "property (self) -> Mapping[LoadKind, Series]",
        "window": "property (self) -> SimulationWindow",
        "per_step_amounts": "(self) -> DataFrame",
        "total_amounts": "(self) -> dict[str, float]",
        "to_dataframe": "(self) -> DataFrame",
        "from_dataframe": "classmethod (cls, frame: DataFrame, *, strategy_name: str, grid_charge_forecast: Literal['pv_blind', 'trailing_14_days', 'perfect_foresight'] | None = None) -> SimulationResults",
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


RELEASED_CALLS: dict[str, str] = {
    "HomeSimulator": "(self, config: HomeConfig, start_date: Timestamp, end_date: Timestamp, *, weather: WeatherProvider) -> SimulationResults",
}

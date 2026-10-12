# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single home simulation combining PV, battery, and load."""

import datetime
import warnings
from collections.abc import Callable, Iterator, Sequence
from dataclasses import MISSING, dataclass, field, fields
from typing import Optional

import pandas as pd
from pandas.api.types import is_float_dtype, is_integer_dtype

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import DispatchStrategy, SelfConsumptionStrategyConfig, build_dispatch_strategy
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import EVConfig
from solar_challenge.flow import EnergyFlowResult, simulate_timestep, simulate_timestep_tou, validate_energy_balance
from solar_challenge.heat_pump import HeatPumpConfig, generate_heat_pump_load, reference_year_lengths
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig, interpolate_to_minute_resolution, simulate_pv_output
from solar_challenge.seg import SEGTariff, calculate_seg_revenue
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from solar_challenge.weather import WeatherProvider, align_tmy_to_index


_YEAR_LENGTHS_IN_HOURS = reference_year_lengths(rows_per_day=24)


HOME_DISPATCH_STRATEGIES: tuple[str, ...] = ("greedy", "tou_optimized")
"""The values of HomeConfig.dispatch_strategy, the dispatch a home asks for by name."""


def refuse_unknown_home_dispatch_strategy(value: object, *, field: str) -> str:
    """Return *value*, given for the home dispatch strategy that *field* names, refusing it unless it is one of HOME_DISPATCH_STRATEGIES.

    Raises:
        ConfigurationError: "Invalid <field> <value!r>; valid values: [...]".
    """
    if not isinstance(value, str) or value not in HOME_DISPATCH_STRATEGIES:
        raise ConfigurationError(f"Invalid {field} {value!r}; valid values: {sorted(HOME_DISPATCH_STRATEGIES)}")
    return value


@dataclass(frozen=True)
class HomeConfig:
    """Configuration for a single home simulation.

    Attributes:
        pv_config: PV system configuration
        load_config: Load profile configuration
        battery_config: Battery configuration (None for PV-only)
        heat_pump_config: Heat pump configuration (None for no heat pump)
        ev_config: EV configuration (None for no EV)
        location: Geographic location for weather data
        name: Optional identifier for the home
        tariff_config: Tariff configuration (None for no cost tracking)
        dispatch_strategy: Battery dispatch strategy, one of HOME_DISPATCH_STRATEGIES

    Raises:
        ConfigurationError: dispatch_strategy is not one of HOME_DISPATCH_STRATEGIES; or the
            home has a battery whose dispatch would ignore a setting: tou_optimized with no
            tariff to dispatch by, or grid_charging its strategy refuses (build_dispatch_strategy).
    """

    pv_config: PVConfig
    load_config: LoadConfig
    battery_config: Optional[BatteryConfig] = None
    heat_pump_config: Optional[HeatPumpConfig] = None
    ev_config: Optional[EVConfig] = None
    location: Location = Location.bristol()
    name: str = ""
    tariff_config: Optional[TariffConfig] = None
    dispatch_strategy: str = "greedy"
    seg_tariff: Optional[SEGTariff] = None
    """Smart Export Guarantee tariff for pricing grid exports.

    When set, simulate_home prices export_revenue using calculate_seg_revenue()
    at this SEG rate (pence/kWh); when None, export_revenue is 0.
    """

    def __post_init__(self) -> None:
        refuse_unknown_home_dispatch_strategy(self.dispatch_strategy, field="dispatch_strategy")
        if self.battery_config is None:
            return
        if _runs_tariff_tou(self):
            if self.tariff_config is None:
                raise ConfigurationError(
                    "dispatch_strategy 'tou_optimized' dispatches the battery by the tariff's rates, "
                    "but there is no tariff; add a tariff or use dispatch_strategy 'greedy'"
                )
            return
        _configured_strategy(self)


def _runs_tariff_tou(config: HomeConfig) -> bool:
    """Whether the home asks for the tariff-rate TOU path: tou_optimized, and its battery, if any, names no strategy of its own.

    The home runs that path only when it has a tariff.
    """
    return config.dispatch_strategy == "tou_optimized" and (
        config.battery_config is None or config.battery_config.dispatch_strategy is None
    )


def _configured_strategy(config: HomeConfig) -> DispatchStrategy:
    """The strategy the home's battery names, self-consumption when it names none or there is no battery, built for its grid_charging at the home's tariff.

    Raises:
        ConfigurationError: build_dispatch_strategy refuses the battery's grid_charging, which
            the strategy would ignore.
    """
    battery = config.battery_config
    return build_dispatch_strategy(
        (None if battery is None else battery.dispatch_strategy) or SelfConsumptionStrategyConfig(),
        grid_charging=None if battery is None else battery.grid_charging,
        tariff=config.tariff_config,
    )


_COLUMN = "column"
_AMOUNT = "step_amount"


@dataclass(frozen=True)
class _StepAmount:
    """How a series' samples become its rows' amounts, under column: a rate per hour (kW) gives the kWh its row delivers; any other sample (£) already is its row's amount."""

    column: str
    per_hour: bool

    def row_amounts(self, series: pd.Series, window: SimulationWindow) -> pd.Series:
        """Each row's amount of series, whose rows window describes."""
        return window.row_energy_kwh(series) if self.per_hour else series


def _power(column: str, energy_column: str) -> dict[str, object]:
    """Metadata of a kW series written under column; its amount is each row's kWh, under energy_column."""
    return {_COLUMN: column, _AMOUNT: _StepAmount(energy_column, per_hour=True)}


def _money(column: str) -> dict[str, object]:
    """Metadata of a £ series written under column; each sample already is its row's amount."""
    return {_COLUMN: column, _AMOUNT: _StepAmount(column, per_hour=False)}


def _level(column: str) -> dict[str, object]:
    """Metadata of a series written under column that holds a level, which has no amount.

    A state of charge or a rate does not add up over time.
    """
    return {_COLUMN: column}


class SeriesRefused(ValueError):
    """SimulationResults' refusal of one of its series; column is the column the series is written under, and reason says why."""

    def __init__(self, column: str, reason: str) -> None:
        super().__init__(f"SimulationResults' {column} series {reason}")
        self.column = column
        self.reason = reason

    def __reduce__(self) -> tuple[type["SeriesRefused"], tuple[str, str], dict[str, object]]:
        """Rebuild through the constructor from the column and the reason, then restore the instance's state, its notes included, so a refusal raised in a fleet's worker process unpickles in its parent as itself."""
        return (type(self), (self.column, self.reason), self.__dict__)


def _refuse_unless_numbers(column: str, series: pd.Series) -> None:
    """Refuse *series*, written under *column*, unless its dtype is an integer's or a float's, which a bool's is not.

    Raises:
        SeriesRefused: Naming the column and the series' dtype.
    """
    if not (is_integer_dtype(series.dtype) or is_float_dtype(series.dtype)):
        raise SeriesRefused(column, f"is of dtype {series.dtype}, not of an integer or a float dtype")


@dataclass(frozen=True)
class SimulationResults:
    """Comprehensive results from a home simulation.

    All series share one DatetimeIndex of evenly spaced rows; window says which
    calendar days it covers and how long each row lasts (one minute for
    simulate_home's results). Each series field's column metadata names the
    column to_dataframe writes it under and from_dataframe reads it from, and
    each series is named that column, whatever it was named when built. Each
    series holds numbers: its dtype is an integer's or a float's, never a
    bool's, and NaN and the infinities are floats. Construction refuses any
    other series with SeriesRefused, naming its column and its dtype.

    Each amount series, every series but the battery_soc and tariff_rate levels,
    holds a number at every minute, as the run's totals sum every minute's amount.
    Construction raises ValueError naming each that holds a NaN, its first NaN's
    timestamp and how many it holds, and per_minute_amounts and total_amounts raise
    the same for one made NaN in place after construction; an infinite sample is kept.

    Attributes:
        generation: PV generation in kW
        demand: Load demand in kW
        self_consumption: Demand met on site, by PV used directly and by battery discharge, in kW
        battery_charge: Power into battery in kW
        battery_discharge: Power out of battery in kW
        battery_soc: Battery state of charge in kWh
        grid_import: Power imported from grid in kW
        grid_export: Power exported to grid in kW
        import_cost: Cost of grid import in £
        export_revenue: Revenue from grid export in £
        tariff_rate: Tariff rate in £/kWh
        strategy_name: Name of the dispatch strategy used
        heat_pump_load: Optional heat pump electrical load in kW (None if no heat pump)
        grid_charge: Optional power stored in the battery from the grid in kW, a part of
            both battery_charge and grid_import (None when tariff_config is None)
    """

    generation: pd.Series = field(metadata=_power("generation_kw", "generation_kwh"))
    demand: pd.Series = field(metadata=_power("demand_kw", "demand_kwh"))
    self_consumption: pd.Series = field(metadata=_power("self_consumption_kw", "self_consumption_kwh"))
    battery_charge: pd.Series = field(metadata=_power("battery_charge_kw", "battery_charge_kwh"))
    battery_discharge: pd.Series = field(metadata=_power("battery_discharge_kw", "battery_discharge_kwh"))
    battery_soc: pd.Series = field(metadata=_level("battery_soc_kwh"))
    grid_import: pd.Series = field(metadata=_power("grid_import_kw", "grid_import_kwh"))
    grid_export: pd.Series = field(metadata=_power("grid_export_kw", "grid_export_kwh"))
    import_cost: pd.Series = field(metadata=_money("import_cost_gbp"))
    export_revenue: pd.Series = field(metadata=_money("export_revenue_gbp"))
    tariff_rate: pd.Series = field(metadata=_level("tariff_rate_per_kwh"))
    strategy_name: str = "self_consumption"
    heat_pump_load: Optional[pd.Series] = field(default=None, metadata=_power("heat_pump_load_kw", "heat_pump_load_kwh"))
    # Per-timestep slice of import_cost spent charging the battery from the grid, in £
    # (None when tariff_config is None).
    grid_charge_cost: Optional[pd.Series] = field(default=None, metadata=_money("grid_charge_cost_gbp"))
    grid_charge: Optional[pd.Series] = field(default=None, metadata=_power("grid_charge_kw", "grid_charge_kwh"))

    def __post_init__(self) -> None:
        """Name each set series after its column, without renaming the series it was built from, and refuse a NaN amount.

        Raises:
            SeriesRefused: The first set series, in declaration order, whose dtype is no
                integer's or float's; it names the series' column and its dtype.
            ValueError: If an amount series holds a NaN, naming each such series' column, its first
                NaN and when, and how many of its minutes are NaN.
        """
        for name, column in self._series_columns():
            series = getattr(self, name)
            if series is not None:
                _refuse_unless_numbers(column, series)
                object.__setattr__(self, name, series.rename(column))
        self._refuse_nan_amounts()

    @classmethod
    def _series_columns(cls) -> Iterator[tuple[str, str]]:
        """Each series field's name and column, in declaration order."""
        for attribute in fields(cls):
            if _COLUMN in attribute.metadata:
                yield attribute.name, attribute.metadata[_COLUMN]

    @property
    def window(self) -> SimulationWindow:
        """The window the results' index describes: the calendar days it covers, how long each row lasts, and its zone.

        Raises:
            ValueError: If SimulationWindow.of_index refuses the index: it is not a
                DatetimeIndex, it is empty, it has one row and no fixed-duration freq, or its
                rows are not evenly spaced.
        """
        return SimulationWindow.of_index(self.generation.index)

    def _series_with_amounts(self) -> Iterator[tuple[str, pd.Series, _StepAmount]]:
        """Each set series that has an amount, in declaration order: its column, the series and how its samples become its rows' amounts."""
        for attribute in fields(self):
            amount = attribute.metadata.get(_AMOUNT)
            series = getattr(self, attribute.name)
            if isinstance(amount, _StepAmount) and series is not None:
                yield attribute.metadata[_COLUMN], series, amount

    def _refuse_nan_amounts(self) -> None:
        """Raise ValueError naming each amount series that holds a NaN: its column, its first NaN and when, and how many."""
        refused: list[str] = []
        for column, series, _ in self._series_with_amounts():
            missing = series.isna().to_numpy()
            if missing.any():
                first = int(missing.argmax())
                refused.append(
                    f"{column}={series.iloc[first]} at {series.index[first]} ({missing.sum()} of {missing.size} minutes)"
                )
        if refused:
            raise ValueError(
                "SimulationResults' amount series are what its totals sum, so each holds a number at every minute: "
                f"got {', '.join(refused)}"
            )

    def _amount_series(self) -> Iterator[tuple[str, pd.Series]]:
        """Each amount's column and each row's amount, in declaration order, for every series that is set.

        Refuses a NaN amount first, as construction does, since a series can be written in place after it.
        """
        self._refuse_nan_amounts()
        window = self.window
        for _, series, amount in self._series_with_amounts():
            yield amount.column, amount.row_amounts(series, window)

    def per_minute_amounts(self) -> pd.DataFrame:
        """Each row's energy in kWh, window.row_energy_kwh of its kW, and money in £, one column per amount, so a period's totals are its column sums.

        The battery state of charge and the tariff rate have no column, as neither adds up over
        time, and nor has an optional series that is None.

        Raises:
            ValueError: As window does, for an index no window describes; or if an amount series
                holds a NaN written in place after construction, with the message construction raises.
        """
        return pd.concat(dict(self._amount_series()), axis=1)

    def total_amounts(self) -> dict[str, float]:
        """The run's total of each amount: per_minute_amounts' column sums, keyed by column.

        Raises:
            ValueError: As window does, for an index no window describes; or if an amount series
                holds a NaN written in place after construction, with the message construction raises.
        """
        return {column: float(amounts.sum()) for column, amounts in self._amount_series()}

    def to_dataframe(self) -> pd.DataFrame:
        """Convert results to a DataFrame with one column per series that is set."""
        return pd.DataFrame(
            {
                column: series
                for name, column in self._series_columns()
                if (series := getattr(self, name)) is not None
            }
        )

    @classmethod
    def from_dataframe(cls, frame: pd.DataFrame, *, strategy_name: str) -> "SimulationResults":
        """Build the results whose to_dataframe() is frame, simulated under strategy_name.

        Optional series whose column is absent are None.

        Raises:
            ValueError: If frame lacks any required series' column, naming each one, or if an
                amount column holds a NaN, which construction refuses.
            SeriesRefused: If a column is not numbers, as construction refuses its series; it
                names the first such column and its dtype.
        """
        required_fields = {
            attribute.name
            for attribute in fields(cls)
            if attribute.default is MISSING and attribute.default_factory is MISSING
        }
        missing_columns = [
            column
            for name, column in cls._series_columns()
            if name in required_fields and column not in frame.columns
        ]
        if missing_columns:
            raise ValueError(f"frame lacks required series columns: {', '.join(missing_columns)}")
        return cls(
            strategy_name=strategy_name,
            **{name: frame[column] for name, column in cls._series_columns() if column in frame.columns},
        )


@dataclass
class SummaryStatistics:
    """Summary statistics for a simulation period.

    All energy values in kWh, all financial values in £.
    """

    total_generation_kwh: float
    total_demand_kwh: float
    total_self_consumption_kwh: float
    total_grid_import_kwh: float
    total_grid_export_kwh: float
    total_battery_charge_kwh: float
    total_battery_discharge_kwh: float
    peak_generation_kw: float
    peak_demand_kw: float
    self_consumption_ratio: float  # self_consumption / generation
    grid_dependency_ratio: float  # grid_import / demand
    export_ratio: float  # grid_export / generation
    simulation_days: int
    total_import_cost_gbp: float  # total cost of grid imports in £
    total_export_revenue_gbp: float  # total revenue from grid exports in £
    net_cost_gbp: float  # net cost (import - export) in £
    strategy_name: str = "self_consumption"
    seg_revenue_gbp: Optional[float] = None
    total_heat_pump_load_kwh: Optional[float] = None  # total heat pump consumption
    peak_heat_pump_load_kw: Optional[float] = None  # peak heat pump load
    heat_pump_load_ratio: Optional[float] = None  # heat_pump_load / total_demand
    # Slice of total_import_cost_gbp spent charging the battery from the grid: householder
    # import, informational, in no CBS equation (docs/cost-recovery-finance-model.md §4).
    total_grid_charge_cost_gbp: float = 0.0
    # Energy the battery stored from the grid: a part of both total_battery_charge_kwh and
    # total_grid_import_kwh.
    total_grid_charge_kwh: float = 0.0
    # The window the totals were computed over, whose days simulation_days is.
    window: Optional[SimulationWindow] = None

    def __post_init__(self) -> None:
        """Refuse a total_grid_charge_kwh that is not a part of both the battery charge and the grid import, and, when a window is set, a simulation_days other than its days."""
        grid_charge = self.total_grid_charge_kwh
        if not (0.0 <= grid_charge <= self.total_battery_charge_kwh and grid_charge <= self.total_grid_import_kwh):
            raise ValueError(
                "SummaryStatistics' total_grid_charge_kwh is a part of both total_battery_charge_kwh and "
                "total_grid_import_kwh, so it is at least 0 and at most each: "
                f"got total_grid_charge_kwh={grid_charge!r}, "
                f"total_battery_charge_kwh={self.total_battery_charge_kwh!r}, "
                f"total_grid_import_kwh={self.total_grid_import_kwh!r}"
            )
        window = self.window
        if window is not None and self.simulation_days != window.days:
            raise ValueError(
                "SummaryStatistics' simulation_days is the number of calendar days its window covers: "
                f"got simulation_days={self.simulation_days!r} for a window of {window.days} days, "
                f"{window.first_day.isoformat()} to {window.last_day.isoformat()}"
            )

    @property
    def total_pv_charge_kwh(self) -> float:
        """Energy the battery stored from PV, in kWh: its total charge less the part it stored from the grid."""
        return self.total_battery_charge_kwh - self.total_grid_charge_kwh

    @property
    def total_direct_self_consumption_kwh(self) -> float:
        """PV the home used directly, in kWh: its self-consumption less the battery's discharge, which self-consumption counts too."""
        return self.total_self_consumption_kwh - self.total_battery_discharge_kwh

    @property
    def total_grid_to_demand_kwh(self) -> float:
        """Grid import that met demand, in kWh: the total import less the part the battery stored."""
        return self.total_grid_import_kwh - self.total_grid_charge_kwh


def self_consumption_ratio(*, self_consumption_kwh: float, generation_kwh: float) -> float:
    """The share of the generation that was self-consumed, or 0.0 when the generation is not positive."""
    return _share(self_consumption_kwh, generation_kwh)


def grid_dependency_ratio(*, grid_import_kwh: float, demand_kwh: float) -> float:
    """The share of the demand that was imported from the grid, or 0.0 when the demand is not positive."""
    return _share(grid_import_kwh, demand_kwh)


def heat_pump_load_ratio(*, heat_pump_load_kwh: float, demand_kwh: float) -> float:
    """The share of the demand that was the heat pump's load, or 0.0 when the demand is not positive."""
    return _share(heat_pump_load_kwh, demand_kwh)


def _share(part: float, whole: float) -> float:
    """part / whole, or 0.0 when whole is not positive."""
    return float(part / whole) if whole > 0 else 0.0


def _hourly_weather(config: HomeConfig, weather: WeatherProvider) -> pd.DataFrame:
    """The hourly weather a run uses: weather's for config.location, asked once.

    Raises:
        ValueError: If the home has a heat pump and the weather is not one year of hourly rows.
    """
    frame = weather.get(config.location)
    if config.heat_pump_config is not None and len(frame) not in _YEAR_LENGTHS_IN_HOURS:
        raise ValueError(
            f"the weather for {config.location!r} has {len(frame):,} rows, not one year of hourly rows "
            f"({_YEAR_LENGTHS_IN_HOURS.start:,} to {_YEAR_LENGTHS_IN_HOURS[-1]:,}): a heat pump's "
            "annual_heat_demand_kwh is shared out over the heating degree-minutes of this whole year, "
            "so give simulate_home a provider whose weather is one TMY year of hourly rows, as PvgisTmy's is."
        )
    return frame


@dataclass(frozen=True)
class _Demand:
    """A run's demand in kW on its minutes: the household's load, EV charging included, plus any heat pump's load.

    heat_pump_kw is None without a heat pump.
    """

    total_kw: pd.Series
    heat_pump_kw: Optional[pd.Series]


def _heat_pump_load(
    heat_pump: HeatPumpConfig,
    hourly_temperature_c: pd.Series,
    minutes: pd.DatetimeIndex,
) -> pd.Series:
    """The heat pump's electrical load in kW on minutes.

    Its annual heat demand is shared out over the whole TMY year's air temperature.
    """
    minute_temperature = interpolate_to_minute_resolution(hourly_temperature_c)
    return generate_heat_pump_load(
        heat_pump, align_tmy_to_index(minute_temperature, minutes), annual_temperature_c=minute_temperature
    )


def _demand(config: HomeConfig, weather: pd.DataFrame, window: SimulationWindow) -> _Demand:
    """The home's demand on window's rows, with any heat pump run on weather."""
    household_kw = generate_load_profile(config.load_config, window, ev_config=config.ev_config)
    if config.heat_pump_config is None:
        return _Demand(household_kw, None)
    heat_pump_kw = _heat_pump_load(config.heat_pump_config, weather["temp_air"], household_kw.index)
    return _Demand(household_kw + heat_pump_kw, heat_pump_kw)


_Timestep = Callable[[Optional[Battery], pd.Timestamp, float, float], EnergyFlowResult]
"""One row of a run's dispatch, which charges and discharges the run's battery, if it has one.

From that battery and the row's timestamp, generation in kW and demand in kW, to the row's flows.
"""


@dataclass(frozen=True)
class _DispatchPath:
    """How a run dispatches each row, and the strategy name its results record."""

    strategy_name: str
    timestep: _Timestep


def _tariff_tou_timestep(tariff: TariffConfig, step_minutes: float) -> _Timestep:
    """Each row, step_minutes long, dispatched at the tariff's rates by simulate_timestep_tou."""

    def timestep(
        battery: Optional[Battery], timestamp: pd.Timestamp, generation_kw: float, demand_kw: float
    ) -> EnergyFlowResult:
        return simulate_timestep_tou(
            generation_kw=generation_kw,
            demand_kw=demand_kw,
            battery=battery,
            timestamp=timestamp,
            tariff=tariff,
            timestep_minutes=step_minutes,
        )

    return timestep


def _strategy_timestep(strategy: DispatchStrategy, tariff: Optional[TariffConfig], step_minutes: float) -> _Timestep:
    """Each row, step_minutes long, dispatched by strategy through simulate_timestep, which grid-charges by tariff's rates."""

    def timestep(
        battery: Optional[Battery], timestamp: pd.Timestamp, generation_kw: float, demand_kw: float
    ) -> EnergyFlowResult:
        return simulate_timestep(
            generation_kw=generation_kw,
            demand_kw=demand_kw,
            battery=battery,
            timestep_minutes=step_minutes,
            timestamp=timestamp.to_pydatetime(),
            strategy=strategy,
            tariff=tariff,
        )

    return timestep


def _dispatch_path(
    config: HomeConfig, step_minutes: float, strategy: Optional[DispatchStrategy] = None
) -> _DispatchPath:
    """How the home dispatches each row, step_minutes long.

    A given strategy dispatches it, at the home's tariff. Without one, the home takes the
    tariff-rate TOU path when it asks for tou_optimized, has a tariff and its battery names no
    strategy of its own; otherwise its battery's strategy, self-consumption by default.
    """
    tariff = config.tariff_config
    if strategy is not None:
        return _DispatchPath(strategy.name, _strategy_timestep(strategy, tariff, step_minutes))
    if _runs_tariff_tou(config) and tariff is not None:
        return _DispatchPath("tou_optimized", _tariff_tou_timestep(tariff, step_minutes))
    strategy = _configured_strategy(config)
    return _DispatchPath(strategy.name, _strategy_timestep(strategy, tariff, step_minutes))


def _row_flows(
    timestep: _Timestep,
    battery_config: Optional[BatteryConfig],
    generation_kw: pd.Series,
    demand_kw: pd.Series,
    validate_balance: bool,
) -> list[EnergyFlowResult]:
    """Each row's flows, in order, from timestep run on that row's generation and demand.

    The run's battery, built from battery_config when it is set, carries its state of charge
    from each row to the next. With validate_balance, each row's flows are checked for
    energy balance before the next row runs, so an imbalance stops the run at the row it occurs.
    """
    battery = None if battery_config is None else Battery(battery_config)
    flows: list[EnergyFlowResult] = []
    for timestamp, generation, demand in zip(demand_kw.index, generation_kw, demand_kw, strict=True):
        flow = timestep(battery, timestamp, float(generation), float(demand))
        if validate_balance:
            validate_energy_balance(flow)
        flows.append(flow)
    return flows


@dataclass(frozen=True)
class _ImportPricing:
    """Each row's tariff rate in £/kWh, import cost in £ and grid-charging cost in £, None on an untariffed run."""

    tariff_rate: pd.Series
    import_cost: pd.Series
    grid_charge_cost: Optional[pd.Series]


def _price_imports(
    tariff: Optional[TariffConfig],
    flows: Sequence[EnergyFlowResult],
    rows: pd.DatetimeIndex,
) -> _ImportPricing:
    """Each row's import priced at the tariff's rate for that row.

    An untariffed run's rates and costs are 0.0, and it prices no grid charging.
    """
    if tariff is None:
        return _ImportPricing(
            tariff_rate=pd.Series([0.0] * len(flows), index=rows),
            import_cost=pd.Series([0.0] * len(flows), index=rows),
            grid_charge_cost=None,
        )
    rates = [tariff.get_rate(timestamp) for timestamp in rows]
    return _ImportPricing(
        tariff_rate=pd.Series(rates, index=rows),
        import_cost=pd.Series(
            [flow.grid_import * rate for flow, rate in zip(flows, rates, strict=True)], index=rows
        ),
        grid_charge_cost=pd.Series(
            [flow.grid_charge * rate for flow, rate in zip(flows, rates, strict=True)], index=rows
        ),
    )


def _export_revenue(
    seg_tariff: Optional[SEGTariff],
    flows: Sequence[EnergyFlowResult],
    rows: pd.DatetimeIndex,
) -> pd.Series:
    """Each row's export valued at the SEG rate, never the import rate, or at nothing without an SEG."""
    if seg_tariff is None:
        return pd.Series([0.0] * len(flows), index=rows)
    return pd.Series([calculate_seg_revenue(flow.grid_export, seg_tariff) for flow in flows], index=rows)


def _results(
    flows: Sequence[EnergyFlowResult],
    rows: pd.DatetimeIndex,
    *,
    step_hours: float,
    import_pricing: _ImportPricing,
    export_revenue: pd.Series,
    heat_pump_load: Optional[pd.Series],
    strategy_name: str,
) -> SimulationResults:
    """The run's results on its rows, each lasting step_hours hours.

    Each flow's power in kW, the battery's state of charge in kWh, and the run's prices.
    """
    kw_per_kwh = 1 / step_hours

    def power_kw(row_kwh: Callable[[EnergyFlowResult], float]) -> pd.Series:
        return pd.Series([row_kwh(flow) * kw_per_kwh for flow in flows], index=rows)

    return SimulationResults(
        strategy_name=strategy_name,
        generation=power_kw(lambda flow: flow.generation),
        demand=power_kw(lambda flow: flow.demand),
        self_consumption=power_kw(lambda flow: flow.self_consumption),
        battery_charge=power_kw(lambda flow: flow.battery_charge),
        battery_discharge=power_kw(lambda flow: flow.battery_discharge),
        battery_soc=pd.Series([flow.battery_soc for flow in flows], index=rows),
        grid_import=power_kw(lambda flow: flow.grid_import),
        grid_export=power_kw(lambda flow: flow.grid_export),
        import_cost=import_pricing.import_cost,
        export_revenue=export_revenue,
        tariff_rate=import_pricing.tariff_rate,
        heat_pump_load=heat_pump_load,
        grid_charge_cost=import_pricing.grid_charge_cost,
        grid_charge=None if import_pricing.grid_charge_cost is None else power_kw(lambda flow: flow.grid_charge),
    )


def _local_date(moment: pd.Timestamp, timezone: str) -> datetime.date:
    """moment's date on timezone's clock; a naive moment is read as already on it."""
    local_date: datetime.date = (moment if moment.tz is None else moment.tz_convert(timezone)).date()
    return local_date


def _run_window(location: Location, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationWindow:
    """The run's window: the dates of start_date and end_date on location's clock, both counted, at one minute."""
    return SimulationWindow(
        _local_date(start_date, location.timezone),
        _local_date(end_date, location.timezone),
        ONE_MINUTE,
        location.timezone,
    )


def simulate_home(
    config: HomeConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    validate_balance: bool = True,
    *,
    weather: WeatherProvider,
    strategy: Optional[DispatchStrategy] = None,
) -> SimulationResults:
    """Simulate a single home for a date range.

    Args:
        config: Home configuration with PV, load, and optional battery
        start_date: The run's first day: its date on config.location's clock,
            a naive date read as already on that clock
        end_date: The run's last day, counted, read as start_date is
        validate_balance: Whether to validate energy balance each timestep
        weather: Supplies the hourly weather at config.location, which
            simulate_home asks it for once. A heat pump's
            annual_heat_demand_kwh is shared out over the heating
            degree-minutes of the air temperature across this whole year,
            so with a heat pump configured the weather must be one year of
            hourly rows, 8760 to 8784 (365 to 366 days).
        strategy: The dispatch strategy to run the battery under in place of
            the one config selects; None runs config's. It is driven through
            flow.simulate_timestep with config's tariff, so it is offered a
            GridChargeContext exactly when a configured strategy is: with a
            tariff and battery_config.grid_charging. The results'
            strategy_name is its name.

    Returns:
        SimulationResults with every time series on the run's window's rows:
        one a minute on config.location's clock, from the first day's local
        midnight up to the midnight after the last day

    Raises:
        ValueError: If end_date's date is before start_date's, naming both;
            or if a heat pump is configured and the weather is not one year
            of hourly rows.
        LookupError: If weather holds none for config.location, as a
            PrefetchedWeather refuses it. Whatever else weather.get raises,
            e.g. PvgisTmy's WeatherDataError, propagates too.
    """
    window = _run_window(config.location, start_date, end_date)
    rows = window.rows()
    hourly_weather = _hourly_weather(config, weather)
    minute_generation = interpolate_to_minute_resolution(
        simulate_pv_output(config.pv_config, config.location, hourly_weather)
    )
    demand = _demand(config, hourly_weather, window)
    generation_kw = align_tmy_to_index(minute_generation, rows)
    dispatch = _dispatch_path(config, window.step_minutes, strategy)
    flows = _row_flows(dispatch.timestep, config.battery_config, generation_kw, demand.total_kw, validate_balance)
    import_pricing = _price_imports(config.tariff_config, flows, rows)
    export_revenue = _export_revenue(config.seg_tariff, flows, rows)
    if config.tariff_config is not None and config.seg_tariff is None:
        warnings.warn(
            "tariff_config is set but seg_tariff is None: export_revenue will be 0.0. "
            "Configure HomeConfig.seg_tariff to value grid exports at the SEG/export rate.",
            UserWarning,
            stacklevel=2,
        )
    return _results(
        flows,
        rows,
        step_hours=window.step_hours,
        import_pricing=import_pricing,
        export_revenue=export_revenue,
        heat_pump_load=demand.heat_pump_kw,
        strategy_name=dispatch.strategy_name,
    )


def calculate_summary(
    results: SimulationResults,
    seg_tariff_pence_per_kwh: Optional[float] = None,
) -> SummaryStatistics:
    """Calculate summary statistics from simulation results.

    Args:
        results: Simulation results with time series
        seg_tariff_pence_per_kwh: Smart Export Guarantee tariff in pence per kWh.
            If provided, ``seg_revenue_gbp`` is computed from total grid export
            via ``calculate_seg_revenue``.  Must be >= 0; negative values raise
            ``ValueError`` (enforced by ``SEGTariff`` validation — a behaviour
            change from the previous inline formula that silently returned a
            negative number).

    Returns:
        SummaryStatistics with totals and ratios, carrying the window its results
        cover, whose calendar days are its simulation_days

    Notes:
        **Two-path SEG design** — ``total_export_revenue_gbp`` and
        ``seg_revenue_gbp`` are independent figures that can legitimately differ:

        * ``total_export_revenue_gbp`` is always ``results.export_revenue.sum()``.
          When ``simulate_home`` was called with ``HomeConfig.seg_tariff`` set,
          every export timestep was already priced at that SEG rate, so
          ``total_export_revenue_gbp`` already reflects SEG pricing and is the
          authoritative revenue figure for that simulation.

        * ``seg_revenue_gbp`` is an *additional*, independent recalculation
          driven by ``seg_tariff_pence_per_kwh``.  This path exists for callers
          (``fleet.py``, ``output.py``) that build ``SimulationResults`` by hand
          and need a standalone SEG revenue figure without access to a
          ``HomeConfig``.

        **Recommended usage when** ``HomeConfig.seg_tariff`` **was set:**
        read ``total_export_revenue_gbp`` for the authoritative revenue and do
        *not* pass ``seg_tariff_pence_per_kwh`` — or pass the same rate as a
        consistency cross-check.  Passing a *different* rate will produce
        ``seg_revenue_gbp != total_export_revenue_gbp``, which is not an error
        but may mislead callers that compare the two.
    """
    totals = results.total_amounts()
    total_gen = totals["generation_kwh"]
    total_demand = totals["demand_kwh"]
    total_self = totals["self_consumption_kwh"]
    total_import = totals["grid_import_kwh"]
    total_export = totals["grid_export_kwh"]
    total_charge = totals["battery_charge_kwh"]
    total_discharge = totals["battery_discharge_kwh"]

    peak_gen = float(results.generation.max())
    peak_demand = float(results.demand.max())

    # Calculate financial totals
    total_import_cost = totals["import_cost_gbp"]
    total_export_revenue = totals["export_revenue_gbp"]
    net_cost = total_import_cost - total_export_revenue

    # Calculate SEG revenue if tariff is provided.
    # Routed through SEGTariff + calculate_seg_revenue — single source of SEG math.
    # SEGTariff validates rate >= 0; negative values raise ValueError here.
    seg_revenue_gbp: Optional[float] = None
    if seg_tariff_pence_per_kwh is not None:
        seg_revenue_gbp = calculate_seg_revenue(
            total_export,
            SEGTariff(name="", rate_pence_per_kwh=seg_tariff_pence_per_kwh),
        )

    # Grid-charge cost: the slice of total_import_cost spent charging the battery from the grid
    total_grid_charge_cost = totals["grid_charge_cost_gbp"] if results.grid_charge_cost is not None else 0.0
    total_grid_charge = totals["grid_charge_kwh"] if results.grid_charge is not None else 0.0

    # Calculate heat pump metrics if heat pump load is present
    total_heat_pump_kwh: Optional[float] = None
    peak_heat_pump_kw: Optional[float] = None
    heat_pump_ratio: Optional[float] = None
    if results.heat_pump_load is not None:
        total_heat_pump_kwh = totals["heat_pump_load_kwh"]
        peak_heat_pump_kw = float(results.heat_pump_load.max())
        heat_pump_ratio = heat_pump_load_ratio(heat_pump_load_kwh=total_heat_pump_kwh, demand_kwh=total_demand)

    window = results.window
    return SummaryStatistics(
        total_generation_kwh=total_gen,
        total_demand_kwh=total_demand,
        total_self_consumption_kwh=total_self,
        total_grid_import_kwh=total_import,
        total_grid_export_kwh=total_export,
        total_battery_charge_kwh=total_charge,
        total_battery_discharge_kwh=total_discharge,
        peak_generation_kw=peak_gen,
        peak_demand_kw=peak_demand,
        self_consumption_ratio=self_consumption_ratio(self_consumption_kwh=total_self, generation_kwh=total_gen),
        grid_dependency_ratio=grid_dependency_ratio(grid_import_kwh=total_import, demand_kwh=total_demand),
        export_ratio=_share(total_export, total_gen),
        simulation_days=window.days,
        total_import_cost_gbp=total_import_cost,
        total_export_revenue_gbp=total_export_revenue,
        net_cost_gbp=net_cost,
        strategy_name=results.strategy_name,
        seg_revenue_gbp=seg_revenue_gbp,
        total_heat_pump_load_kwh=total_heat_pump_kwh,
        peak_heat_pump_load_kw=peak_heat_pump_kw,
        heat_pump_load_ratio=heat_pump_ratio,
        total_grid_charge_cost_gbp=total_grid_charge_cost,
        total_grid_charge_kwh=total_grid_charge,
        window=window,
    )

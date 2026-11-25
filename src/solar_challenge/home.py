# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single home simulation combining PV, battery, and load."""

import datetime
import warnings
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import MISSING, dataclass, field, fields
from typing import Optional

import pandas as pd
from pandas.api.types import is_float_dtype, is_integer_dtype

from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.demand import DemandInputs, LoadKind, PerLoad, compose_demand, first_differing_row, row_at
from solar_challenge.dispatch import (
    DispatchStrategy,
    GridChargeForecast,
    SelfConsumptionStrategyConfig,
    build_dispatch_strategy,
    refuse_grid_charging_it_would_ignore,
)
from solar_challenge.ev import EVConfig, require_tariff_for_smart_charging
from solar_challenge.flow import EnergyFlowResult, simulate_timestep, validate_energy_balance
from solar_challenge.grid_charge_forecast import grid_charge_ceilings_kwh
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.number_fields import NON_NEGATIVE, as_finite_float, read_field
from solar_challenge.pv import PVConfig, interpolate_to_minute_resolution, simulate_pv_output
from solar_challenge.seg import SEGTariff, calculate_seg_revenue
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from solar_challenge.weather import WeatherProvider, align_tmy_to_index


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

    Raises:
        ConfigurationError: ev_config's smart_charging_mode is 'off_peak' and there is no
            tariff_config whose cheap minutes it charges in (require_tariff_for_smart_charging);
            or the home has a battery whose dispatch strategy build_dispatch_strategy refuses:
            tou_optimized on the tariff's clock with no tariff; grid_charging the strategy would
            ignore, a tariff with no cheap period included; or tou_optimized whose peak_hours
            reach a cheap minute of tariff_config.
    """

    pv_config: PVConfig
    load_config: LoadConfig
    battery_config: Optional[BatteryConfig] = None
    heat_pump_config: Optional[HeatPumpConfig] = None
    ev_config: Optional[EVConfig] = None
    location: Location = Location.bristol()
    name: str = ""
    tariff_config: Optional[TariffConfig] = None
    seg_tariff: Optional[SEGTariff] = None
    """Smart Export Guarantee tariff for pricing grid exports.

    When set, simulate_home prices export_revenue using calculate_seg_revenue()
    at this SEG rate (pence/kWh); when None, export_revenue is 0.
    """

    def __post_init__(self) -> None:
        if self.ev_config is not None:
            require_tariff_for_smart_charging(self.ev_config, self.tariff_config)
        if self.battery_config is not None:
            _battery_strategy(self, self.battery_config)


def _battery_strategy(config: HomeConfig, battery: BatteryConfig) -> DispatchStrategy:
    """A new instance of battery's dispatch strategy, built for its grid_charging at the home's tariff.

    Raises:
        ConfigurationError: build_dispatch_strategy's refusals: tou_optimized on the tariff's
            clock with no tariff; peak_hours that reach a cheap minute of the tariff; or
            grid_charging the strategy would ignore.
    """
    return build_dispatch_strategy(
        battery.dispatch_strategy,
        grid_charging=battery.grid_charging,
        tariff=config.tariff_config,
    )


_COLUMN = "column"
_AMOUNT = "step_amount"

_HOUSEHOLD_TOLERANCE_KW = 1e-9
"""How far below zero the household's load, demand less the additional loads, may fall in a row, in kW: the rounding of adding loads up into demand."""


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


def _refuse_unless_a_number_in_every_row(column: str, series: pd.Series) -> None:
    """Refuse *series*, an amount written under *column*, unless it holds a number in every row, as the run's totals sum every row's amount; a NaN, or an NA in a nullable series, is none.

    Raises:
        SeriesRefused: Naming the column, how many of its rows hold no number, and the first one's
            value and index label.
    """
    missing = series.isna().to_numpy()
    if missing.any():
        first = int(missing.argmax())
        raise SeriesRefused(
            column,
            f"holds no number in {missing.sum()} of its {missing.size} rows, though the run's totals sum every "
            f"row's amount; the first is {series.iloc[first]}, at {series.index[first]}",
        )


def _refuse_unless_an_amount(column: str, series: pd.Series) -> None:
    """Refuse *series*, an amount written under *column*, unless it is numbers with a number in every row.

    Raises:
        SeriesRefused: As _refuse_unless_numbers, then _refuse_unless_a_number_in_every_row, does.
    """
    _refuse_unless_numbers(column, series)
    _refuse_unless_a_number_in_every_row(column, series)


@dataclass(frozen=True)
class RunPricing:
    """How simulate_home priced a run's grid flows.

    A rate is None when no tariff, or no SEG tariff, priced its flow. A £0 tariff is 0.0,
    and priced.

    Attributes:
        import_tariff_mean_rate_gbp_per_kwh: The import tariff's rate in £/kWh, time-weighted
            over the run's rows
        seg_rate_pence_per_kwh: The SEG rate in pence/kWh that the run's export earned

    Raises:
        ConfigurationError: A ValueError naming the field and the value, for a set rate that is
            not a finite number of at least 0.
    """

    import_tariff_mean_rate_gbp_per_kwh: Optional[float]
    seg_rate_pence_per_kwh: Optional[float]

    def __post_init__(self) -> None:
        """Read each set rate as a finite number of at least 0, holding the float read, as SEGTariff reads its rate."""
        read_field(self, "import_tariff_mean_rate_gbp_per_kwh", as_finite_float, NON_NEGATIVE, optional=True)
        read_field(self, "seg_rate_pence_per_kwh", as_finite_float, NON_NEGATIVE, optional=True)


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
    holds a number in every row, as the run's totals sum every row's amount.
    Construction, after its dtype refusal, and per_step_amounts, total_amounts
    and to_dataframe, since a series can still be written in place, refuse the
    first amount series holding a NaN, or an NA in a nullable series, with
    SeriesRefused, naming its column, how many of its rows hold no number and
    the first; an infinite sample is kept.

    Attributes:
        generation: PV generation in kW
        demand: Load demand in kW
        self_consumption: Demand met on site, by PV used directly and by battery discharge, in kW
        battery_charge: Power the battery drew from the bus to charge, before its charge losses, in kW
        battery_discharge: Power out of battery in kW
        battery_soc: Battery state of charge in kWh
        grid_import: Power imported from grid in kW
        grid_export: Power exported to grid in kW
        import_cost: Cost of grid import in £
        export_revenue: Revenue from grid export in £
        tariff_rate: Tariff rate in £/kWh
        strategy_name: Name of the dispatch strategy used
        heat_pump_load: The heat pump's electrical load in kW, None without a heat pump;
            transitional, it is one series with additional_loads[LoadKind.HEAT_PUMP]
        grid_charge: Optional power the battery drew from the grid in kW, a part of
            both battery_charge and grid_import (None when tariff_config is None)
        pricing: How the run's grid flows were priced (None for results simulate_home did
            not make, e.g. from_dataframe's)
        grid_charge_forecast: The forecast that sized the run's grid charge in cheap
            periods, its battery's GridChargeConfig.forecast (None when the run did not
            grid-charge)
        additional_loads: The loads within demand besides the household's, in kW, by
            LoadKind, each on demand's rows and written under its kind's column; held as a
            PerLoad, its keys read by LoadKind.parse. Construction refuses, with
            SeriesRefused, a household entry, a heat_pump_load that differs from its heat
            pump entry, an entry off demand's rows, and additional loads that exceed demand
            by more than 1e-9 kW in a row, naming that row. loads holds the household's
            load, demand less these, beside them.
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
    heat_pump_load: Optional[pd.Series] = None
    # Per-timestep slice of import_cost spent charging the battery from the grid, in £
    # (None when tariff_config is None).
    grid_charge_cost: Optional[pd.Series] = field(default=None, metadata=_money("grid_charge_cost_gbp"))
    grid_charge: Optional[pd.Series] = field(default=None, metadata=_power("grid_charge_kw", "grid_charge_kwh"))
    pricing: Optional[RunPricing] = None
    grid_charge_forecast: Optional[GridChargeForecast] = None
    additional_loads: Mapping[LoadKind, pd.Series] = field(default_factory=lambda: PerLoad({}))

    def __post_init__(self) -> None:
        """Name each set series after its column, without renaming the series it was built from, and settle the additional loads.

        Raises:
            SeriesRefused: The first set series, in declaration order, whose dtype is no
                integer's or float's; it names the series' column and its dtype. Or else an
                additional load refused as the class docstring says. Or else the first amount
                series holding no number in a row (see the class docstring). Or else the
                first row where the additional loads exceed demand.
            ValueError: As LoadKind.parse does, for an additional load keyed by no load kind.
        """
        for name, column in self._series_columns():
            series = getattr(self, name)
            if series is not None:
                _refuse_unless_numbers(column, series)
                object.__setattr__(self, name, series.rename(column))
        self._settle_additional_loads()
        self._refuse_amounts_missing_a_number()
        self._refuse_additional_loads_above_demand()

    def _settle_additional_loads(self) -> None:
        """Hold additional_loads as a PerLoad holding heat_pump_load, each on demand's index and named its kind's column, and heat_pump_load as its heat pump entry.

        Each load is refused on its own (its dtype, then a row holding no number) before it is
        compared with heat_pump_load or demand's rows.
        """
        loads = dict(PerLoad(self.additional_loads))
        if LoadKind.HOUSEHOLD in loads:
            raise SeriesRefused(
                LoadKind.HOUSEHOLD.column, "is demand less the additional loads, so it is never one of them"
            )
        for kind, load in loads.items():
            _refuse_unless_an_amount(kind.column, load)
        heat_pump = self.heat_pump_load
        if heat_pump is not None:
            _refuse_unless_an_amount(LoadKind.HEAT_PUMP.column, heat_pump)
            if not loads.setdefault(LoadKind.HEAT_PUMP, heat_pump).equals(heat_pump):
                raise SeriesRefused(
                    LoadKind.HEAT_PUMP.column,
                    "differs from heat_pump_load, which is additional_loads' heat pump load: give one of them, "
                    "or both as one series",
                )
        rows = self.demand.index
        for kind, load in loads.items():
            position = first_differing_row(load.index, rows)
            if position is not None:
                raise SeriesRefused(
                    kind.column,
                    f"is not on demand's rows: they first differ at row {position:,}, where it has "
                    f"{row_at(load.index, position)} and demand has {row_at(rows, position)}",
                )
            loads[kind] = load.set_axis(rows).rename(kind.column)
        settled = PerLoad(loads)
        object.__setattr__(self, "additional_loads", settled)
        object.__setattr__(self, "heat_pump_load", settled.get(LoadKind.HEAT_PUMP))

    def _household_kw(self) -> pd.Series:
        """Demand less the additional loads, on demand's rows, named the household's column."""
        household = self.demand
        for load in self.additional_loads.values():
            household = household - load
        return household.rename(LoadKind.HOUSEHOLD.column)

    def _refuse_additional_loads_above_demand(self) -> None:
        """Refuse the first row whose household load, demand less the additional loads, is below -_HOUSEHOLD_TOLERANCE_KW.

        Raises:
            SeriesRefused: Naming the household's column, its load in that row and the row.
        """
        household = self._household_kw()
        below = (household < -_HOUSEHOLD_TOLERANCE_KW).to_numpy()
        if below.any():
            first = int(below.argmax())
            raise SeriesRefused(
                LoadKind.HOUSEHOLD.column,
                f"is demand less the additional loads ({', '.join(kind.column for kind in self.additional_loads)}), "
                f"so at least 0, but it is {household.iloc[first]} kW at {household.index[first]}: "
                "the additional loads are parts of demand, so they never exceed it",
            )

    @property
    def loads(self) -> Mapping[LoadKind, pd.Series]:
        """Every load within demand in kW, by LoadKind: the household's, demand less the additional loads and at least 0, then each additional load."""
        household = self._household_kw().clip(lower=0.0)
        return PerLoad({LoadKind.HOUSEHOLD: household, **self.additional_loads})

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
        """Each set series that has an amount, in declaration order, then each additional load in LoadKind order: its column, the series and how its samples become its rows' amounts."""
        for attribute in fields(self):
            amount = attribute.metadata.get(_AMOUNT)
            series = getattr(self, attribute.name)
            if isinstance(amount, _StepAmount) and series is not None:
                yield attribute.metadata[_COLUMN], series, amount
        for kind, load in self.additional_loads.items():
            yield kind.column, load, _StepAmount(kind.energy_column, per_hour=True)

    def _refuse_amounts_missing_a_number(self) -> None:
        """Refuse the first set amount series, in declaration order, that holds no number in a row (see the class docstring).

        Raises:
            SeriesRefused: As _refuse_unless_a_number_in_every_row does.
        """
        for column, series, _ in self._series_with_amounts():
            _refuse_unless_a_number_in_every_row(column, series)

    def _amount_series(self) -> Iterator[tuple[str, pd.Series]]:
        """Each amount's column and each row's amount, in declaration order, for every series that is set."""
        self._refuse_amounts_missing_a_number()
        window = self.window
        for _, series, amount in self._series_with_amounts():
            yield amount.column, amount.row_amounts(series, window)

    def per_step_amounts(self) -> pd.DataFrame:
        """Each row's energy in kWh, window.row_energy_kwh of its kW, and money in £, one column per amount, so a period's totals are its column sums.

        The battery state of charge and the tariff rate have no column, as neither adds up over
        time, and nor has an optional series that is None.

        Raises:
            ValueError: As window does, for an index no window describes.
            SeriesRefused: The first amount series holding no number in a row (see the class
                docstring).
        """
        return pd.concat(dict(self._amount_series()), axis=1)

    def total_amounts(self) -> dict[str, float]:
        """The run's total of each amount: per_step_amounts' column sums, keyed by column.

        Raises:
            ValueError: As window does, for an index no window describes.
            SeriesRefused: The first amount series holding no number in a row (see the class
                docstring).
        """
        return {column: float(amounts.sum()) for column, amounts in self._amount_series()}

    def to_dataframe(self) -> pd.DataFrame:
        """Convert results to a DataFrame with one column per series that is set, then one per additional load under its kind's column.

        Raises:
            SeriesRefused: The first amount series holding no number in a row (see the class
                docstring).
        """
        self._refuse_amounts_missing_a_number()
        return pd.DataFrame(
            {
                **{
                    column: series
                    for name, column in self._series_columns()
                    if (series := getattr(self, name)) is not None
                },
                **{kind.column: load for kind, load in self.additional_loads.items()},
            }
        )

    @classmethod
    def from_dataframe(
        cls, frame: pd.DataFrame, *, strategy_name: str, grid_charge_forecast: Optional[GridChargeForecast] = None
    ) -> "SimulationResults":
        """Build the results whose to_dataframe() is frame, simulated under strategy_name, its grid charge sized by grid_charge_forecast.

        Optional series whose column is absent are None, and additional_loads holds each
        additional load kind whose column frame has.

        Raises:
            ValueError: If frame lacks any required series' column; the message names each one.
            SeriesRefused: If a column is not numbers, as construction refuses its series; it
                names the first such column and its dtype. Or else, as construction refuses
                it, the first amount column holding no number in a row (see the class docstring).
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
            grid_charge_forecast=grid_charge_forecast,
            additional_loads={
                kind: frame[kind.column]
                for kind in LoadKind
                if kind is not LoadKind.HOUSEHOLD and kind.column in frame.columns
            },
            **{name: frame[column] for name, column in cls._series_columns() if column in frame.columns},
        )


@dataclass(frozen=True)
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
    # Energy the battery delivered to the home's bus, after its discharge losses: a part of
    # total_self_consumption_kwh, which counts it.
    total_battery_discharge_kwh: float
    peak_generation_kw: float
    peak_demand_kw: float
    self_consumption_ratio: float  # self_consumption / generation
    grid_dependency_ratio: float  # grid_import / demand
    export_ratio: float  # grid_export / generation
    # The window the totals were computed over, as calculate_summary takes it from the results.
    window: SimulationWindow
    total_import_cost_gbp: float  # total cost of grid imports in £
    total_export_revenue_gbp: float  # total revenue from grid exports in £
    net_cost_gbp: float  # net cost (import - export) in £
    strategy_name: str = "self_consumption"
    total_heat_pump_load_kwh: Optional[float] = None  # total heat pump consumption
    peak_heat_pump_load_kw: Optional[float] = None  # peak heat pump load
    heat_pump_load_ratio: Optional[float] = None  # heat_pump_load / total_demand
    # Slice of total_import_cost_gbp spent charging the battery from the grid: householder
    # import, informational, in no CBS equation (docs/cost-recovery-finance-model.md §4).
    total_grid_charge_cost_gbp: float = 0.0
    # Energy the battery drew from the grid, before its charge losses: a part of both
    # total_battery_charge_kwh and total_grid_import_kwh.
    total_grid_charge_kwh: float = 0.0
    # How the run's grid flows were priced, None when that is unknown.
    pricing: Optional[RunPricing] = None
    # The forecast that sized the run's grid charge in cheap periods; None when the run did
    # not grid-charge, or its stored summary predates the field.
    grid_charge_forecast: Optional[GridChargeForecast] = None

    def __post_init__(self) -> None:
        """Refuse a window that is not a SimulationWindow, a total_grid_charge_kwh that is not a part of both the battery charge and the grid import, and a total_battery_discharge_kwh above the self-consumption that counts it."""
        if not isinstance(self.window, SimulationWindow):
            raise ValueError(
                "SummaryStatistics' window is the SimulationWindow its totals were computed over, which "
                f"calculate_summary takes from the results: got window={self.window!r}"
            )
        grid_charge = self.total_grid_charge_kwh
        if not (0.0 <= grid_charge <= self.total_battery_charge_kwh and grid_charge <= self.total_grid_import_kwh):
            raise ValueError(
                "SummaryStatistics' total_grid_charge_kwh is a part of both total_battery_charge_kwh and "
                "total_grid_import_kwh, so it is at least 0 and at most each: "
                f"got total_grid_charge_kwh={grid_charge!r}, "
                f"total_battery_charge_kwh={self.total_battery_charge_kwh!r}, "
                f"total_grid_import_kwh={self.total_grid_import_kwh!r}"
            )
        discharge = self.total_battery_discharge_kwh
        if not discharge <= self.total_self_consumption_kwh:
            raise ValueError(
                "SummaryStatistics' total_battery_discharge_kwh is a part of total_self_consumption_kwh, which "
                "counts the battery's discharge, so it is at most it: "
                f"got total_battery_discharge_kwh={discharge!r}, "
                f"total_self_consumption_kwh={self.total_self_consumption_kwh!r}"
            )

    @property
    def simulation_days(self) -> int:
        """The number of calendar days the summary's window covers."""
        return self.window.days

    @property
    def total_pv_charge_kwh(self) -> float:
        """Energy the battery drew from PV, in kWh: its total charge less the part it drew from the grid."""
        return self.total_battery_charge_kwh - self.total_grid_charge_kwh

    @property
    def total_direct_self_consumption_kwh(self) -> float:
        """PV the home used directly, in kWh: its self-consumption less the battery's discharge, which self-consumption counts too, so at least 0."""
        return self.total_self_consumption_kwh - self.total_battery_discharge_kwh

    @property
    def total_grid_to_demand_kwh(self) -> float:
        """Grid import that met demand, in kWh: the total import less the part the battery drew."""
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


_Timestep = Callable[[Optional[Battery], datetime.datetime, float, float, Optional[float]], EnergyFlowResult]
"""One row of a run's dispatch, which charges and discharges the run's battery, if it has one.

From that battery and the row's timestamp, generation in kW, demand in kW and useful-charge
ceiling in kWh (None when the row's grid charge has none), to the row's flows.
"""


@dataclass(frozen=True)
class _DispatchPath:
    """How a run dispatches each row, and the strategy name its results record."""

    strategy_name: str
    timestep: _Timestep


def _strategy_timestep(strategy: DispatchStrategy, tariff: Optional[TariffConfig], step_minutes: float) -> _Timestep:
    """Each row, step_minutes long, dispatched by strategy through simulate_timestep, which grid-charges by tariff's rates up to the row's useful-charge ceiling."""

    def timestep(
        battery: Optional[Battery],
        timestamp: datetime.datetime,
        generation_kw: float,
        demand_kw: float,
        ceiling_kwh: Optional[float],
    ) -> EnergyFlowResult:
        return simulate_timestep(
            generation_kw=generation_kw,
            demand_kw=demand_kw,
            battery=battery,
            timestep_minutes=step_minutes,
            timestamp=timestamp,
            strategy=strategy,
            tariff=tariff,
            useful_charge_ceiling_kwh=ceiling_kwh,
        )

    return timestep


def _settling_timestep(step_minutes: float) -> _Timestep:
    """Each row, step_minutes long, of a run with no battery, which simulate_timestep only settles with the grid; the row's ceiling has nothing to cap."""

    def timestep(
        battery: Optional[Battery],
        timestamp: datetime.datetime,
        generation_kw: float,
        demand_kw: float,
        ceiling_kwh: Optional[float],
    ) -> EnergyFlowResult:
        return simulate_timestep(
            generation_kw=generation_kw, demand_kw=demand_kw, battery=None, timestep_minutes=step_minutes
        )

    return timestep


def _dispatch_path(
    config: HomeConfig, step_minutes: float, strategy: Optional[DispatchStrategy] = None
) -> _DispatchPath:
    """How the home dispatches each row, step_minutes long, at its tariff.

    A home with a battery runs strategy when given, else its battery's _battery_strategy. A home
    with no battery runs none: it only settles each row, and is named after strategy when given,
    else after self-consumption.

    Raises:
        ConfigurationError: strategy is given and would ignore the battery's grid_charging, as
            refuse_grid_charging_it_would_ignore refuses it.
    """
    if config.battery_config is None:
        name = strategy.name if strategy is not None else SelfConsumptionStrategyConfig().strategy_type
        return _DispatchPath(name, _settling_timestep(step_minutes))
    if strategy is not None:
        refuse_grid_charging_it_would_ignore(
            strategy, grid_charging=config.battery_config.grid_charging, tariff=config.tariff_config
        )
    else:
        strategy = _battery_strategy(config, config.battery_config)
    return _DispatchPath(strategy.name, _strategy_timestep(strategy, config.tariff_config, step_minutes))


def _grid_charge_forecast(config: HomeConfig) -> Optional[GridChargeForecast]:
    """The forecast that sizes the home's grid charge in cheap periods: its battery's, None when its battery does not grid-charge."""
    battery = config.battery_config
    return None if battery is None or battery.grid_charging is None else battery.grid_charging.forecast


def _grid_charge_ceilings(
    config: HomeConfig, generation_kw: pd.Series, demand_kw: pd.Series
) -> tuple[Optional[float], ...]:
    """Each row's useful-charge ceiling, from the run's generation and demand, under the forecast that sizes the home's grid charge.

    Every row's is None when the home's battery does not grid-charge at a tariff.
    """
    battery, tariff = config.battery_config, config.tariff_config
    if battery is None or battery.grid_charging is None or tariff is None:
        return (None,) * len(generation_kw)
    return grid_charge_ceilings_kwh(battery.grid_charging.forecast, generation_kw, demand_kw, battery, tariff)


def _row_flows(
    timestep: _Timestep,
    battery_config: Optional[BatteryConfig],
    generation_kw: pd.Series,
    demand_kw: pd.Series,
    ceilings_kwh: Sequence[Optional[float]],
    validate_balance: bool,
) -> list[EnergyFlowResult]:
    """Each row's flows, in order, from timestep run on that row's generation, demand and useful-charge ceiling.

    The run's battery, built from battery_config when it is set, carries its state of charge
    from each row to the next. With validate_balance, each row's flows are checked for
    energy balance before the next row runs, so an imbalance stops the run at the row it occurs.
    """
    battery = None if battery_config is None else Battery(battery_config)
    flows: list[EnergyFlowResult] = []
    for timestamp, generation, demand, ceiling in zip(
        demand_kw.index.to_pydatetime(), generation_kw, demand_kw, ceilings_kwh, strict=True
    ):
        flow = timestep(battery, timestamp, float(generation), float(demand), ceiling)
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
    rates = tariff.rates_for(rows)
    return _ImportPricing(
        tariff_rate=pd.Series(rates, index=rows),
        import_cost=pd.Series([flow.grid_import for flow in flows], index=rows) * rates,
        grid_charge_cost=pd.Series([flow.grid_charge for flow in flows], index=rows) * rates,
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


def _run_pricing(config: HomeConfig, tariff_rate: pd.Series) -> RunPricing:
    """How config's tariffs priced the run whose rows' import rates are tariff_rate.

    The rows are the run's evenly spaced minutes, so their mean rate is the tariff's
    time-weighted mean over the run.
    """
    seg_tariff = config.seg_tariff
    return RunPricing(
        import_tariff_mean_rate_gbp_per_kwh=None if config.tariff_config is None else float(tariff_rate.mean()),
        seg_rate_pence_per_kwh=None if seg_tariff is None else seg_tariff.rate_pence_per_kwh,
    )


def _results(
    flows: Sequence[EnergyFlowResult],
    rows: pd.DatetimeIndex,
    *,
    step_hours: float,
    import_pricing: _ImportPricing,
    export_revenue: pd.Series,
    additional_loads: Mapping[LoadKind, pd.Series],
    strategy_name: str,
    pricing: RunPricing,
    grid_charge_forecast: Optional[GridChargeForecast],
) -> SimulationResults:
    """The run's results on its rows, each lasting step_hours hours.

    Each flow's power in kW, the battery's state of charge in kWh, the run's prices,
    pricing, how they were priced, and grid_charge_forecast, what sized its grid charge.
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
        grid_charge_cost=import_pricing.grid_charge_cost,
        grid_charge=None if import_pricing.grid_charge_cost is None else power_kw(lambda flow: flow.grid_charge),
        pricing=pricing,
        grid_charge_forecast=grid_charge_forecast,
        additional_loads=additional_loads,
    )


def _local_date(moment: pd.Timestamp, timezone: str) -> datetime.date:
    """moment's date on timezone's clock; a naive moment is read as already on it."""
    local_date: datetime.date = (moment if moment.tz is None else moment.tz_convert(timezone)).date()
    return local_date


def run_window(location: Location, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationWindow:
    """The window simulate_home runs a home at location over: the dates of start_date and end_date on location's clock, a naive moment read as already on it, both counted, at one minute."""
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
            the one config selects; None runs its battery's own
            (_battery_strategy). It is driven through
            flow.simulate_timestep with config's tariff, so it is offered a
            GridChargeContext exactly when a configured strategy is: with a
            tariff and battery_config.grid_charging, each row's carrying the
            same useful-charge ceiling. The results' strategy_name is its name.
            It is refused when battery_config sets grid_charging and its
            charges_from_the_grid is False.

    The home's demand is its household's load plus any EV's charging, which
    generate_ev_charging_profile places on the home's tariff, a 'solar' EV
    on the home's own PV generation, plus any heat pump's load.

    Each cheap period's grid charge fills the battery to its target, or to
    the period's useful-charge ceiling when that is lower: grid_charge_ceilings_kwh
    under battery_config.grid_charging's forecast, from the run's generation and
    demand (docs/grid-charge-forecast.md). Under 'pv_blind' no period has a
    ceiling.

    Returns:
        SimulationResults with every time series on the run's window's rows:
        one a minute on config.location's clock, from the first day's local
        midnight up to the midnight after the last day; their pricing records
        the rates config's tariffs priced the run's grid flows at, and their
        grid_charge_forecast the forecast that sized its grid charge, None
        when the battery does not grid-charge

    Raises:
        ValueError: If end_date's date is before start_date's, naming both;
            or, as compose_demand refuses it, if a heat pump is configured and
            the weather is not one year of hourly rows.
        ConfigurationError: If strategy is given, battery_config sets
            grid_charging and the strategy does not charge from the grid
            (refuse_grid_charging_it_would_ignore); raised before weather is
            asked for, naming grid_charging and the strategy.
        LookupError: If weather holds none for config.location, as a
            PrefetchedWeather refuses it. Whatever else weather.get raises,
            e.g. PvgisTmy's WeatherDataError, propagates too.
    """
    window = run_window(config.location, start_date, end_date)
    rows = window.rows()
    dispatch = _dispatch_path(config, window.step_minutes, strategy)
    hourly_weather = weather.get(config.location)
    minute_generation = interpolate_to_minute_resolution(
        simulate_pv_output(config.pv_config, config.location, hourly_weather)
    )
    demand = compose_demand(
        config.load_config,
        config.heat_pump_config,
        config.ev_config,
        DemandInputs(window, hourly_weather["temp_air"], minute_generation, config.tariff_config),
    )
    generation_kw = align_tmy_to_index(minute_generation, rows)
    ceilings_kwh = _grid_charge_ceilings(config, generation_kw, demand.total_kw)
    flows = _row_flows(
        dispatch.timestep, config.battery_config, generation_kw, demand.total_kw, ceilings_kwh, validate_balance
    )
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
        additional_loads=demand.additional(),
        strategy_name=dispatch.strategy_name,
        pricing=_run_pricing(config, import_pricing.tariff_rate),
        grid_charge_forecast=_grid_charge_forecast(config),
    )


def calculate_summary(results: SimulationResults) -> SummaryStatistics:
    """Calculate summary statistics from simulation results.

    Args:
        results: Simulation results with time series

    Returns:
        SummaryStatistics with totals and ratios, carrying the window its results
        cover, whose calendar days are its simulation_days, the results' pricing and
        the forecast that sized their grid charge
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
        window=results.window,
        total_import_cost_gbp=total_import_cost,
        total_export_revenue_gbp=total_export_revenue,
        net_cost_gbp=net_cost,
        strategy_name=results.strategy_name,
        total_heat_pump_load_kwh=total_heat_pump_kwh,
        peak_heat_pump_load_kw=peak_heat_pump_kw,
        heat_pump_load_ratio=heat_pump_ratio,
        total_grid_charge_cost_gbp=total_grid_charge_cost,
        total_grid_charge_kwh=total_grid_charge,
        pricing=results.pricing,
        grid_charge_forecast=results.grid_charge_forecast,
    )

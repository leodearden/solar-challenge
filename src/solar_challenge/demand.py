# SPDX-License-Identifier: AGPL-3.0-or-later
"""The loads a home's demand is made of, each named by its kind, and their composition from the home's load, heat pump and EV."""

import functools
import operator
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Optional, TypeVar

import numpy as np
import pandas as pd

from solar_challenge.ev import EVConfig, RowWeights, generate_ev_charging_profile
from solar_challenge.heat_pump import HeatPumpConfig, generate_heat_pump_load
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.pv import interpolate_to_minute_resolution
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import HOURS_PER_DAY, SimulationWindow, describe_first_differing_row, year_row_counts
from solar_challenge.weather import align_tmy_to_index

V = TypeVar("V")


class LoadKind(StrEnum):
    """One of the loads a home's demand is made of; its value names its chart role."""

    HOUSEHOLD = "household"
    HEAT_PUMP = "heat_pump"
    EV = "ev"

    @property
    def column(self) -> str:
        """The column its power in kW is written under."""
        return f"{self.value}_load_kw"

    @property
    def energy_column(self) -> str:
        """The column its energy in kWh is written under."""
        return f"{self.value}_load_kwh"

    @property
    def label(self) -> str:
        """How a report names it."""
        return _LABELS[self]

    @classmethod
    def parse(cls, value: object) -> "LoadKind":
        """The kind whose value *value* is; ValueError, naming it and every kind's value, for anything else."""
        if isinstance(value, str):
            for kind in cls:
                if kind.value == value:
                    return kind
        values = [repr(kind.value) for kind in cls]
        raise ValueError(
            f"{value!r} is not a load kind: the load kinds are {', '.join(values[:-1])} and {values[-1]}"
        )


_LABELS: Mapping[LoadKind, str] = MappingProxyType({
    LoadKind.HOUSEHOLD: "Household",
    LoadKind.HEAT_PUMP: "Heat pump",
    LoadKind.EV: "EV charging",
})


class PerLoad(Mapping[LoadKind, V]):
    """A read-only mapping of a value per load kind, held in LoadKind order whatever the order it was given in."""

    __slots__ = ("_items",)

    def __init__(self, by_kind: Mapping[Any, V]) -> None:
        """Hold a copy of *by_kind*, each key read by LoadKind.parse, which refuses one naming no kind."""
        given = {LoadKind.parse(key): value for key, value in by_kind.items()}
        self._items: dict[LoadKind, V] = {kind: given[kind] for kind in LoadKind if kind in given}

    def __getitem__(self, kind: LoadKind) -> V:
        return self._items[kind]

    def __iter__(self) -> Iterator[LoadKind]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return hash(tuple(self._items.items()))

    def __repr__(self) -> str:
        return f"PerLoad({self._items!r})"

    def __reduce__(self) -> tuple[type["PerLoad[V]"], tuple[dict[LoadKind, V]]]:
        """Rebuild through the constructor from a dict of the items, so a copy reads its keys as the original did."""
        return (type(self), (dict(self._items),))


@dataclass(frozen=True)
class DemandInputs:
    """What a home's loads are placed by, besides their own settings.

    Attributes:
        window: The rows the loads are on
        hourly_temperature_c: One TMY year of hourly air temperature, which a heat pump's
            annual heat demand is shared out over
        minute_generation_kw: The home's PV generation over that TMY year at one minute, which
            a 'solar' EV charges in the most of
        tariff: The home's import tariff, which an off-peak EV charges in the cheapest of
    """

    window: SimulationWindow
    hourly_temperature_c: pd.Series
    minute_generation_kw: pd.Series
    tariff: Optional[TariffConfig]


@dataclass(frozen=True)
class Demand:
    """A home's demand on its window's rows, load by load: the household's always, and any heat pump's and EV's.

    Construction holds loads as a PerLoad. It refuses, with ValueError, loads without the
    household's, and a load whose index is not window.rows(), naming its kind and the first
    row that differs.
    """

    window: SimulationWindow
    loads: Mapping[LoadKind, pd.Series]

    def __post_init__(self) -> None:
        """Hold loads as a PerLoad, once each is on the window's rows and the household's is among them."""
        loads = PerLoad(self.loads)
        if LoadKind.HOUSEHOLD not in loads:
            raise ValueError(
                f"a home's demand always holds its {LoadKind.HOUSEHOLD.value!r} load, "
                f"but the loads given are {[kind.value for kind in loads]}"
            )
        rows = self.window.rows()
        for kind, load in loads.items():
            _refuse_unless_on_rows(kind, load.index, rows)
        object.__setattr__(self, "loads", loads)

    @property
    def total_kw(self) -> pd.Series:
        """The home's demand in kW on the window's rows: its loads summed, on each read, so bind it once."""
        total: pd.Series = functools.reduce(operator.add, self.loads.values())
        return total

    def additional(self) -> PerLoad[pd.Series]:
        """Every load but the household's."""
        return PerLoad({kind: load for kind, load in self.loads.items() if kind is not LoadKind.HOUSEHOLD})


def _refuse_unless_on_rows(kind: LoadKind, index: pd.Index, rows: pd.DatetimeIndex) -> None:
    """Refuse the *kind* load, on *index*, unless index is the window's *rows*, naming the first row that differs."""
    difference = describe_first_differing_row(index, rows, "the window")
    if difference is not None:
        raise ValueError(f"the {kind.value} load is not on its window's rows: {difference}")


def compose_demand(
    load: LoadConfig,
    heat_pump: Optional[HeatPumpConfig],
    ev: Optional[EVConfig],
    inputs: DemandInputs,
) -> Demand:
    """A home's demand on inputs.window's rows: its household's load, plus any heat pump's, run on inputs' temperature, plus any EV's charging, placed on inputs' tariff, a 'solar' EV's in the most of inputs' generation.

    Each load is named its kind's column.

    Raises:
        ValueError: If a heat pump is given and inputs.hourly_temperature_c is not one year of
            hourly rows, naming its row count.
    """
    window = inputs.window
    loads = {LoadKind.HOUSEHOLD: generate_load_profile(load, window)}
    if heat_pump is not None:
        loads[LoadKind.HEAT_PUMP] = _heat_pump_load(heat_pump, inputs.hourly_temperature_c, window.rows())
    if ev is not None:
        loads[LoadKind.EV] = generate_ev_charging_profile(
            ev, window, tariff=inputs.tariff, generation_kw=_generation_on(inputs.minute_generation_kw)
        )
    return Demand(window, {kind: series.rename(kind.column) for kind, series in loads.items()})


def _heat_pump_load(
    heat_pump: HeatPumpConfig,
    hourly_temperature_c: pd.Series,
    minutes: pd.DatetimeIndex,
) -> pd.Series:
    """The heat pump's electrical load in kW on minutes.

    Its annual heat demand is shared out over the whole TMY year's air temperature.

    Raises:
        ValueError: If hourly_temperature_c is not one year of hourly rows, naming its row count.
    """
    year_hours = year_row_counts(HOURS_PER_DAY)
    if len(hourly_temperature_c) not in year_hours:
        raise ValueError(
            f"the weather's air temperature has {len(hourly_temperature_c):,} rows, not one year of hourly rows "
            f"({year_hours.start:,} to {year_hours[-1]:,}): a heat pump's annual_heat_demand_kwh is shared out "
            "over the heating degree-minutes of this whole year, so run it on one TMY year of hourly weather, "
            "as PvgisTmy's is."
        )
    minute_temperature = interpolate_to_minute_resolution(hourly_temperature_c)
    return generate_heat_pump_load(
        heat_pump, align_tmy_to_index(minute_temperature, minutes), annual_temperature_c=minute_temperature
    )


def _generation_on(minute_generation: pd.Series) -> RowWeights:
    """The home's PV generation in kW on whatever rows it is given, read from its TMY-year *minute_generation* by UTC time of year."""

    def generation_kw(rows: pd.DatetimeIndex) -> np.ndarray:
        on_rows: np.ndarray = align_tmy_to_index(minute_generation, rows).to_numpy()
        return on_rows

    return generation_kw

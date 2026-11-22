# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each cheap window's useful-charge ceiling, from a run's PV and demand: how far a cheap period's grid charge may fill a battery before the PV after it would strand the charge.

A cheap window is a maximal run of rows the tariff prices cheap, TariffConfig.cheap_minutes_of_day
read on each row's wall-clock minute. Its horizon runs from its first row to the next window's
first row, or to the run's end. Over a horizon the battery follows the TOU tariff-clock rule: it
holds through the window's rows, then stores every PV surplus, at most max_charge_kw and less its
charge loss, and covers every shortfall, at most max_discharge_kw and plus its discharge loss,
within its SoH-derated SOC envelope. useful_charge_ceiling_kwh turns those flows into the highest
start SOC whose extra charge the horizon's PV will not strand.

StepLimits bounds every dispatcher's discharge by the shortfall, so for a dispatcher other than
tou_optimized the model over-states the discharge, which only raises the ceiling, toward PV-blind.

grid_charge_ceilings_kwh gives each row of a run its window's ceiling under a GridChargeForecast.
docs/grid-charge-forecast.md records the method and its measurement.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Optional, assert_never

import numpy as np
import numpy.typing as npt
import pandas as pd

from solar_challenge.battery import BatteryConfig, SocEnvelope
from solar_challenge.dispatch import GridChargeForecast
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import SimulationWindow, minutes_of_day

TRAILING_DAYS: Final = 14
"""How many earlier windows of the same clock trailing_14_days reads; docs/grid-charge-forecast.md §3 says why."""

CEILING_QUANTILE: Final = 0.75
"""The quantile of their ceilings trailing_14_days fills to; docs/grid-charge-forecast.md §3 says why."""

GRID_CHARGE_FORECAST_LABELS: Final[Mapping[GridChargeForecast, str]] = MappingProxyType(
    {
        "pv_blind": "each cheap period fills the battery to its grid-charge target, whatever PV the day brings",
        "trailing_14_days": (
            "the 75th percentile of the useful charge the same cheap window needed on each of the 14 days before it"
        ),
        "perfect_foresight": (
            "the useful charge each cheap window needed, read from the run's own future PV and demand: "
            "an upper bound for analysis, never a board figure"
        ),
    }
)
"""What sizes a cheap period's grid charge under each forecast, in plain English, for the reports."""

_Floats = npt.NDArray[np.float64]


def useful_charge_ceiling_kwh(
    inflow_kwh: npt.ArrayLike, outflow_kwh: npt.ArrayLike, *, floor_kwh: float, top_kwh: float
) -> float:
    """The highest start-of-horizon SOC in kWh whose extra charge the horizon's PV will not strand, within [floor_kwh, top_kwh].

    inflow_kwh is the energy each step stores from PV and outflow_kwh the energy it withdraws for a
    shortfall, before the battery clamps its SOC. Charge above the ceiling would still be in the
    battery when PV next fills it, so PV would export in its place; charge at or below it is spent
    first, as the battery empties before it fills, or the battery never fills.

    Raises:
        ValueError: If a flow is not one-dimensional or holds a negative entry, naming it; if the
            flows differ in length, naming both; or if floor_kwh is above top_kwh, naming both.
    """
    inflow, outflow = _horizon_flow("inflow_kwh", inflow_kwh), _horizon_flow("outflow_kwh", outflow_kwh)
    if inflow.shape != outflow.shape:
        raise ValueError(
            f"inflow_kwh and outflow_kwh must be of equal length, got {inflow.size} and {outflow.size} steps"
        )
    if floor_kwh > top_kwh:
        raise ValueError(f"floor_kwh must be at most top_kwh, got floor_kwh={floor_kwh!r} and top_kwh={top_kwh!r}")
    level = np.concatenate(([0.0], np.cumsum(inflow - outflow)))
    peak = np.maximum.accumulate(level)
    never_full = top_kwh - float(peak[-1])
    empties_first = float(np.max(np.minimum(floor_kwh - level, top_kwh - peak)))
    return float(np.clip(max(never_full, empties_first), floor_kwh, top_kwh))


def _horizon_flow(name: str, flow_kwh: npt.ArrayLike) -> _Floats:
    """flow_kwh as a float array, refused unless it is one-dimensional and holds no negative entry."""
    flow = np.asarray(flow_kwh, dtype=np.float64)
    if flow.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional, got shape {flow.shape}")
    if (flow < 0.0).any():
        raise ValueError(f"{name} must hold no negative entry, got {float(flow.min())!r} kWh")
    return flow


@dataclass(frozen=True)
class _CheapWindow:
    """A maximal run of cheap rows, [start, end), the wall-clock minute it opens at, and its horizon's end: the next window's start, or the run's end."""

    start: int
    end: int
    clock: int
    horizon_end: int


@dataclass(frozen=True)
class _Run:
    """A run's cheap windows, and the energy its battery stores from PV and withdraws for shortfalls at each row, per the horizon model."""

    windows: tuple[_CheapWindow, ...]
    inflow_kwh: _Floats
    outflow_kwh: _Floats
    envelope: SocEnvelope


def grid_charge_ceilings_kwh(
    forecast: GridChargeForecast,
    generation_kw: pd.Series,
    demand_kw: pd.Series,
    battery_config: BatteryConfig,
    tariff: TariffConfig,
) -> tuple[Optional[float], ...]:
    """The useful-charge ceiling in kWh of each row of a run, None where its grid charge has none.

    A row outside every cheap window has none, and so does every row under 'pv_blind'. Under
    'perfect_foresight' each window's rows hold its own horizon's ceiling, read from the run's
    future. Under 'trailing_14_days' each window's rows hold the CEILING_QUANTILE of the ceilings
    the TRAILING_DAYS earlier windows opening at the same wall-clock minute needed: each of those
    horizons ended by the time this window opens, since a horizon ends where the next window
    starts. A window with fewer such windows before it has none.

    Args:
        forecast: The GridChargeForecast sizing the battery's grid charge.
        generation_kw: The run's PV generation in kW on its rows.
        demand_kw: The run's demand in kW on the same rows.
        battery_config: The battery, whose power limits, efficiencies and SoH-derated SOC
            envelope the horizon model reads.
        tariff: The tariff whose cheap minutes open the windows.

    Raises:
        ValueError: If generation_kw and demand_kw are not on the same rows; or as
            SimulationWindow.of_index refuses their index.
    """
    if not generation_kw.index.equals(demand_kw.index):
        raise ValueError(
            "generation_kw and demand_kw must be on the same rows, "
            f"got {len(generation_kw)} and {len(demand_kw)} rows that differ"
        )
    windows = _cheap_windows(generation_kw.index, tariff)
    window_ceilings = _window_ceilings(
        forecast, windows, lambda: _run(windows, generation_kw, demand_kw, battery_config)
    )
    return _row_ceilings(len(generation_kw), windows, window_ceilings)


def _cheap_windows(index: pd.DatetimeIndex, tariff: TariffConfig) -> tuple[_CheapWindow, ...]:
    """The maximal runs of rows of index whose wall-clock minute tariff prices cheap, in order."""
    clocks = minutes_of_day(index)
    cheap = np.isin(clocks, np.fromiter(tariff.cheap_minutes_of_day, dtype=np.int64))
    edges = np.diff(np.concatenate(([0], cheap.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    horizon_ends = [*starts[1:], len(index)]
    return tuple(
        _CheapWindow(start=int(start), end=int(end), clock=int(clocks[start]), horizon_end=int(horizon_end))
        for start, end, horizon_end in zip(starts, ends, horizon_ends)
    )


def _run(
    windows: tuple[_CheapWindow, ...], generation_kw: pd.Series, demand_kw: pd.Series, battery_config: BatteryConfig
) -> _Run:
    """The horizon model's flows at each row: in a window's rows the battery holds; after them it stores the PV surplus and covers the shortfall, within its power limits and less its losses."""
    step_hours = SimulationWindow.of_index(generation_kw.index).step_hours
    generation, demand = generation_kw.to_numpy(dtype=np.float64), demand_kw.to_numpy(dtype=np.float64)
    holding = np.zeros(len(generation), dtype=bool)
    for window in windows:
        holding[window.start : window.end] = True
    stored = np.minimum(np.clip(generation - demand, 0.0, None), battery_config.max_charge_kw) * step_hours
    withdrawn = np.minimum(np.clip(demand - generation, 0.0, None), battery_config.max_discharge_kw) * step_hours
    return _Run(
        windows=windows,
        inflow_kwh=np.where(holding, 0.0, stored * battery_config.charge_efficiency),
        outflow_kwh=np.where(holding, 0.0, withdrawn / battery_config.discharge_efficiency),
        envelope=battery_config.soc_envelope(),
    )


def _window_ceilings(
    forecast: GridChargeForecast, windows: tuple[_CheapWindow, ...], run: Callable[[], _Run]
) -> Sequence[Optional[float]]:
    """Each of windows' ceiling under forecast; run builds the horizon model's flows, only for a forecast that reads them."""
    match forecast:
        case "pv_blind":
            return (None,) * len(windows)
        case "perfect_foresight":
            return _own_horizon_ceilings(run())
        case "trailing_14_days":
            return _trailing_ceilings(run())
        case _:
            assert_never(forecast)


def _own_horizon_ceilings(run: _Run) -> tuple[float, ...]:
    """Each window's ceiling over its own horizon, from its first row to the next window's."""
    return tuple(
        useful_charge_ceiling_kwh(
            run.inflow_kwh[window.start : window.horizon_end],
            run.outflow_kwh[window.start : window.horizon_end],
            floor_kwh=run.envelope.min_soc_kwh,
            top_kwh=run.envelope.max_soc_kwh,
        )
        for window in run.windows
    )


def _trailing_ceilings(run: _Run) -> tuple[Optional[float], ...]:
    """Each window's CEILING_QUANTILE of its TRAILING_DAYS last same-clock windows' own ceilings, None before it has that many."""
    earlier_by_clock: defaultdict[int, list[float]] = defaultdict(list)
    ceilings: list[Optional[float]] = []
    for window, own in zip(run.windows, _own_horizon_ceilings(run)):
        analogues = earlier_by_clock[window.clock][-TRAILING_DAYS:]
        ceilings.append(float(np.quantile(analogues, CEILING_QUANTILE)) if len(analogues) == TRAILING_DAYS else None)
        earlier_by_clock[window.clock].append(own)
    return tuple(ceilings)


def _row_ceilings(
    rows: int, windows: tuple[_CheapWindow, ...], window_ceilings: Sequence[Optional[float]]
) -> tuple[Optional[float], ...]:
    """Each of rows' ceiling: its window's, or None outside every window and for a window with none."""
    row_ceilings: list[Optional[float]] = [None] * rows
    for window, ceiling in zip(windows, window_ceilings):
        row_ceilings[window.start : window.end] = [ceiling] * (window.end - window.start)
    return tuple(row_ceilings)

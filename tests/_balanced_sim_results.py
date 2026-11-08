# SPDX-License-Identifier: AGPL-3.0-or-later
"""A home's simulation results row by row on a caller's index, each row balanced on its own,
and a fleet of such homes, for tests that choose every row's flows, e.g. the community netting tests.

Each row's generation and demand are the caller's, and so are its battery charge and discharge,
zero unless given. The grid takes what is left, so that in every row
``generation + grid_import + battery_discharge == demand + grid_export + battery_charge``.
Self-consumption is min(generation, demand), nothing is priced and battery_soc is zero. Every
series is on the index as given, its freq or lack of one included, so a test can hand in an
index no window describes. A test that chooses a run's totals builds it with
tests._finance_builders.make_sim_results instead, and one that needs a daily sine with
tests._sinusoidal_sim_results.

Usage::

    from tests._balanced_sim_results import make_balanced_fleet

    index = pd.date_range("2024-06-21 12:00", periods=2, freq="min", tz="Europe/London")
    fleet = make_balanced_fleet(index, [([3.0, 0.0], [1.0, 1.0]), ([0.0, 0.0], [2.0, 1.0])])
    community = simulate_community(fleet, CommunityConfig(sharing_mode="p2p"))
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from solar_challenge.fleet import FleetResults
from solar_challenge.home import SimulationResults
from tests._finance_builders import make_fleet_results_of


def make_balanced_sim_results(
    index: pd.DatetimeIndex,
    generation: Sequence[float],
    demand: Sequence[float],
    *,
    battery_charge: Sequence[float] | None = None,
    battery_discharge: Sequence[float] | None = None,
) -> SimulationResults:
    """One home's results on *index*: *generation* and *demand* in kW, the battery's
    *battery_charge* and *battery_discharge*, zero unless given, and the grid taking the rest of
    each row, exporting a surplus and importing a shortfall.

    Raises:
        ValueError: A series has another length than *index*; the message names it and both lengths.
    """
    zeros = [0.0] * len(index)
    charge = zeros if battery_charge is None else battery_charge
    discharge = zeros if battery_discharge is None else battery_discharge
    for name, values in (
        ("generation", generation),
        ("demand", demand),
        ("battery_charge", charge),
        ("battery_discharge", discharge),
    ):
        if len(values) != len(index):
            raise ValueError(f"{name} has {len(values)} values but the index has {len(index)} rows")
    rows = list(zip(generation, demand, charge, discharge, strict=True))

    def _series(values: Sequence[float]) -> pd.Series:
        return pd.Series(values, index=index, dtype=float)

    return SimulationResults(
        generation=_series(generation),
        demand=_series(demand),
        self_consumption=_series([min(g, d) for g, d, _, _ in rows]),
        battery_charge=_series(charge),
        battery_discharge=_series(discharge),
        battery_soc=_series(zeros),
        grid_import=_series([max(0.0, d - g + ch - dis) for g, d, ch, dis in rows]),
        grid_export=_series([max(0.0, g - d + dis - ch) for g, d, ch, dis in rows]),
        import_cost=_series(zeros),
        export_revenue=_series(zeros),
        tariff_rate=_series(zeros),
    )


def make_balanced_fleet(
    index: pd.DatetimeIndex,
    per_home_generation_and_demand: Sequence[tuple[Sequence[float], Sequence[float]]],
) -> FleetResults:
    """A fleet of make_balanced_sim_results' results on *index*, one home for each (generation, demand)
    pair of *per_home_generation_and_demand*, paired in order with a default make_home_config home."""
    return make_fleet_results_of(
        [
            make_balanced_sim_results(index, generation, demand)
            for generation, demand in per_home_generation_and_demand
        ]
    )

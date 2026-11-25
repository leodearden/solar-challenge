# SPDX-License-Identifier: AGPL-3.0-or-later
"""load_panels draws a run's loads: no panel for a run whose demand is the household's alone; otherwise the demand-by-load panel, then a profile panel for each additional load, in LoadKind order."""

import dataclasses
from collections.abc import Mapping

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("plotly")
from solar_challenge.demand import LoadKind
from solar_challenge.home import SimulationResults
from solar_challenge.web.charts import COLOUR_PALETTE, load_panels
from tests._finance_builders import make_sim_results
from tests._plotly_figure import traces
from tests._steady_runs import steady_run

_DAY = "2024-06-01"


def _day_run(*, demand_kw: float, additional_loads: Mapping[LoadKind, pd.Series]) -> SimulationResults:
    """One June day at a row a minute, its demand steady at *demand_kw*, which holds each of *additional_loads*."""
    return dataclasses.replace(steady_run(_DAY, _DAY, demand_kw=demand_kw), additional_loads=additional_loads)


def _minutes_of_the_day() -> pd.DatetimeIndex:
    return steady_run(_DAY, _DAY).demand.index


def _heat_pump_and_ev_run() -> SimulationResults:
    """A 4 kW demand holding a heat pump at 1.5 kW until noon and 0.5 kW after, and an EV at 3 kW from 18:00."""
    index = _minutes_of_the_day()
    return _day_run(
        demand_kw=4.0,
        additional_loads={
            LoadKind.HEAT_PUMP: pd.Series(np.where(index.hour < 12, 1.5, 0.5), index=index),
            LoadKind.EV: pd.Series(np.where(index.hour >= 18, 3.0, 0.0), index=index),
        },
    )


def test_a_run_whose_demand_is_the_households_alone_has_no_load_panel() -> None:
    assert load_panels(make_sim_results(days=1)) == ()


def test_a_heat_pump_runs_panels_are_the_demand_by_load_then_the_heat_pumps_profile() -> None:
    index = _minutes_of_the_day()
    panels = load_panels(_day_run(demand_kw=4.0, additional_loads={LoadKind.HEAT_PUMP: pd.Series(1.5, index=index)}))

    assert [panel.dom_id for panel in panels] == ["chart-demand-by-load", "chart-load-profile-heat-pump"]
    pie = traces(panels[0].content)[0]
    # 4 kW less the heat pump's 1.5 kW for 24 h is the household's, and 1.5 kW for 24 h the heat pump's.
    assert pie["labels"] == ["Household", "Heat pump"]
    assert pie["values"] == [60.0, 36.0]


def test_a_heat_pump_and_ev_runs_pie_draws_each_load_in_its_kinds_colour() -> None:
    panels = load_panels(_heat_pump_and_ev_run())

    assert [panel.dom_id for panel in panels] == [
        "chart-demand-by-load",
        "chart-load-profile-heat-pump",
        "chart-load-profile-ev",
    ]
    pie = traces(panels[0].content)[0]
    assert pie["labels"] == ["Household", "Heat pump", "EV charging"]
    assert pie["marker"]["colors"] == [COLOUR_PALETTE["household"], COLOUR_PALETTE["heat_pump"], COLOUR_PALETTE["ev"]]


@pytest.mark.parametrize("kind", [LoadKind.HEAT_PUMP, LoadKind.EV], ids=lambda kind: kind.value)
def test_each_profile_panel_draws_its_loads_kw_at_its_own_instants_in_its_kinds_colour(kind: LoadKind) -> None:
    results = _heat_pump_and_ev_run()
    load = results.additional_loads[kind]
    (profile,) = [panel for panel in load_panels(results) if panel.dom_id == f"chart-load-profile-{kind.value.replace('_', '-')}"]

    (trace,) = traces(profile.content)

    # A day of minute rows is short enough to be drawn as it is.
    assert trace["name"] == kind.label
    assert trace["x"] == [instant.isoformat() for instant in load.index]
    assert trace["y"] == load.tolist()
    assert trace["line"]["color"] == COLOUR_PALETTE[kind.value]

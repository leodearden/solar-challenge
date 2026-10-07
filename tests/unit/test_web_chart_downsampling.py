# SPDX-License-Identifier: AGPL-3.0-or-later
"""A chart of a run's time series draws every step of a run of at most 2000 steps, and for a
longer run the mean of each evenly spaced window. Every chart draws one run at the same
instants, because one rule picks the windows.
"""

import dataclasses
import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("plotly")
from solar_challenge.home import SimulationResults
from solar_challenge.web.charts import (
    battery_soc_chart,
    fleet_aggregate_timeline,
    fleet_grid_impact,
    heat_pump_analysis,
    overlaid_power_flows,
    power_flow_timeline,
)
from tests._finance_builders import make_fleet_results_of, make_sim_results


def _first_steps(results: SimulationResults, count: int) -> SimulationResults:
    """*results* cut to its first *count* steps."""
    return SimulationResults.from_dataframe(results.to_dataframe().head(count), strategy_name=results.strategy_name)


def _with_rising_soc(results: SimulationResults) -> SimulationResults:
    """*results* with a battery SOC that rises at every step, so a window's mean differs from its first step."""
    steps = results.battery_soc.index
    return dataclasses.replace(results, battery_soc=pd.Series(np.arange(len(steps)) / 1000, index=steps))


def _soc_trace(results: SimulationResults) -> dict[str, Any]:
    """The battery SOC trace that battery_soc_chart draws for *results*."""
    return json.loads(battery_soc_chart(results, battery_capacity_kwh=10.0))["data"][0]


@pytest.mark.parametrize("steps", [48, 2000])
def test_a_chart_of_at_most_2000_steps_draws_every_step(steps: int) -> None:
    """The first *steps* hourly steps of a year, two days' 48 or exactly 2000, are drawn as they are."""
    run = _with_rising_soc(_first_steps(make_sim_results(days=365), steps))

    trace = _soc_trace(run)

    assert (trace["x"], trace["y"]) == (
        [step.isoformat() for step in run.battery_soc.index],
        run.battery_soc.round(4).tolist(),
    )


def test_a_chart_of_more_than_2000_steps_draws_the_mean_of_each_evenly_spaced_window() -> None:
    """A year of hourly steps, 8,760 across both DST changes, is drawn as the mean of each window."""
    year = _with_rising_soc(make_sim_results(days=365))

    trace = _soc_trace(year)

    drawn_at = pd.to_datetime(trace["x"], utc=True)
    window = drawn_at[1] - drawn_at[0]
    assert len(drawn_at) < len(year.battery_soc)
    assert set(drawn_at[1:] - drawn_at[:-1]) == {window}
    assert trace["y"] == year.battery_soc.resample(window).mean().round(4).tolist()


def test_every_chart_of_a_runs_time_series_draws_it_at_the_same_instants() -> None:
    """Each chart of a downsampled year draws every trace at the power-flow timeline's instants."""
    base = make_sim_results(days=365)
    year = dataclasses.replace(base, heat_pump_load=pd.Series(0.3, index=base.demand.index))
    fleet = make_fleet_results_of([year])
    heat_pump_charts = heat_pump_analysis(year)
    assert heat_pump_charts is not None

    figures = {
        "power_flow_timeline": power_flow_timeline(year),
        "battery_soc_chart": battery_soc_chart(year, battery_capacity_kwh=10.0),
        "heat_pump_load_profile": heat_pump_charts["cop_chart"],
        "overlaid_power_flows": overlaid_power_flows([year], ["Run A"]),
        "fleet_aggregate_timeline": fleet_aggregate_timeline(fleet),
        "fleet_grid_impact": fleet_grid_impact(fleet),
    }
    instants = {
        name: {tuple(trace["x"]) for trace in json.loads(figure)["data"]}
        for name, figure in figures.items()
    }

    (expected,) = instants["power_flow_timeline"]
    assert len(expected) < len(year.generation)
    assert {name: axes for name, axes in instants.items() if axes != {expected}} == {}

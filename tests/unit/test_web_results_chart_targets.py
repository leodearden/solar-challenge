# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each chart container on a results page is the target of a renderChart call.

static/js/chart-renderer.js's renderChart draws into the element whose id is its first
argument, and draws nothing, silently, when no element has that id. results/home.html and
results/fleet.html write each chart's id twice, on its container and in the call that
draws it. The converse, that each target is a container, is not checked: home.html calls
renderChart for charts whose {% if %} leaves their container out, passing a '{}' figure
that renderChart skips.
"""

import dataclasses
import uuid
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("flask")

from flask import Flask

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import calculate_fleet_summary
from solar_challenge.home import calculate_summary
from solar_challenge.web.storage import RunStorage
from tests._finance_builders import (
    make_fleet_results,
    make_home_config,
    make_sim_results,
)
from tests._html_page import element_ids, render_chart_targets
from tests._web_app import build_test_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return build_test_app(tmp_path)


def _chart_containers(page: str) -> set[str]:
    """The ids of the chart containers of *page*: each element id that starts with 'chart-'."""
    return {
        element_id
        for element_id in element_ids(page)
        if element_id.startswith("chart-")
    }


def test_each_chart_container_on_the_home_results_page_is_the_target_of_a_render_chart_call(
    app: Flask,
) -> None:
    """A year-long run with a battery and a heat-pump load renders all nine chart containers."""
    year = make_sim_results()
    results = dataclasses.replace(
        year, heat_pump_load=pd.Series(0.3, index=year.demand.index)
    )
    run_id = str(uuid.uuid4())
    storage: RunStorage = app.extensions["storage"]
    storage.save_home_run(
        run_id,
        make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0)),
        results,
        calculate_summary(results),
    )

    response = app.test_client().get(f"/results/home/{run_id}")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    chart_containers = _chart_containers(page)
    assert chart_containers == {
        "chart-sankey",
        "chart-daily-balance",
        "chart-power-flow",
        "chart-battery-soc",
        "chart-financial",
        "chart-monthly",
        "chart-seasonal",
        "chart-hp-load-share",
        "chart-hp-load-profile",
    }
    containers_no_call_draws = chart_containers - set(render_chart_targets(page))
    assert containers_no_call_draws == set()


def test_each_chart_container_on_the_fleet_results_page_is_the_target_of_a_render_chart_call(
    app: Flask,
) -> None:
    """A two-home fleet run renders all five chart containers, as any saved fleet run does."""
    fleet = make_fleet_results(n_homes=2, days=1)
    run_id = str(uuid.uuid4())
    storage: RunStorage = app.extensions["storage"]
    storage.save_fleet_run(
        run_id=run_id,
        fleet_results=fleet,
        fleet_summary=calculate_fleet_summary(fleet),
        per_home_summaries=[
            calculate_summary(results) for results in fleet.per_home_results
        ],
    )

    response = app.test_client().get(f"/results/fleet/{run_id}")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    chart_containers = _chart_containers(page)
    assert chart_containers == {
        "chart-aggregate-timeline",
        "chart-grid-impact",
        "chart-heatmap",
        "chart-box-plots",
        "chart-distribution-histograms",
    }
    containers_no_call_draws = chart_containers - set(render_chart_targets(page))
    assert containers_no_call_draws == set()

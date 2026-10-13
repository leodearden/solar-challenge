# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each chart on a results page is drawn from the figure its container carries, so the
page writes each chart's id once.

components/macros.html's chart_panel writes a chart's id on its container, with the
chart's figure in data-chart-figure. static/js/chart-renderer.js draws each container
that carries one, so no script on the page names a chart's id. A chart whose figure has
nothing to draw gets no container.
"""

import dataclasses
import json
import uuid
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("flask")

from flask import Flask

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import calculate_fleet_summary
from solar_challenge.home import SimulationResults, calculate_summary
from solar_challenge.web.storage import RunStorage
from tests._finance_builders import (
    make_fleet_results,
    make_home_config,
    make_sim_results,
)
from tests._html_page import chart_figures, element_ids, script_texts, texts
from tests._web_app import build_test_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return build_test_app(tmp_path)


def _home_results_page(
    app: Flask, results: SimulationResults, battery_config: BatteryConfig | None = None
) -> str:
    """The results page of a run of *results*, saved to *app*'s store for a make_home_config home with *battery_config*'s battery."""
    run_id = str(uuid.uuid4())
    storage: RunStorage = app.extensions["storage"]
    storage.save_home_run(
        run_id,
        make_home_config(battery_config=battery_config),
        results,
        calculate_summary(results),
    )

    response = app.test_client().get(f"/results/home/{run_id}")

    assert response.status_code == 200
    return response.get_data(as_text=True)


def _assert_each_chart_is_drawn_from_the_figure_its_container_carries(
    page: str, chart_ids: set[str]
) -> None:
    """The chart containers of *page*, the elements whose id starts with 'chart-', are those of *chart_ids*; each carries a Plotly figure, and no script names one."""
    figures = chart_figures(page)
    assert {element_id for element_id in element_ids(page) if element_id.startswith("chart-")} == chart_ids
    assert set(figures) == chart_ids
    assert sorted(chart_id for chart_id, figure in figures.items() if "data" not in json.loads(figure)) == []
    scripts = script_texts(page)
    assert sorted(chart_id for chart_id in chart_ids if any(chart_id in script for script in scripts)) == []


def test_each_chart_on_the_home_results_page_is_drawn_from_the_figure_its_container_carries(
    app: Flask,
) -> None:
    """A year-long run with a battery and a heat-pump load draws all nine charts."""
    year = make_sim_results()
    results = dataclasses.replace(
        year, heat_pump_load=pd.Series(0.3, index=year.demand.index)
    )

    page = _home_results_page(app, results, BatteryConfig(capacity_kwh=5.0))

    _assert_each_chart_is_drawn_from_the_figure_its_container_carries(
        page,
        {
            "chart-sankey",
            "chart-daily-balance",
            "chart-power-flow",
            "chart-battery-soc",
            "chart-financial",
            "chart-monthly",
            "chart-seasonal",
            "chart-hp-load-share",
            "chart-hp-load-profile",
        },
    )


def test_each_chart_on_the_fleet_results_page_is_drawn_from_the_figure_its_container_carries(
    app: Flask,
) -> None:
    """A two-home fleet run draws all five charts, as any saved fleet run does."""
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
    _assert_each_chart_is_drawn_from_the_figure_its_container_carries(
        response.get_data(as_text=True),
        {
            "chart-aggregate-timeline",
            "chart-grid-impact",
            "chart-heatmap",
            "chart-box-plots",
            "chart-distribution-histograms",
        },
    )


def test_a_home_run_whose_charts_have_nothing_to_draw_gets_no_container_for_them(
    app: Flask,
) -> None:
    """A one-day run with no energy flow and no battery has nothing to draw in its sankey, battery, monthly, seasonal and heat-pump charts; the seasonal chart's card says why instead."""
    page = _home_results_page(
        app, make_sim_results(self_kwh=0.0, export_kwh=0.0, import_kwh=0.0, days=1)
    )

    _assert_each_chart_is_drawn_from_the_figure_its_container_carries(
        page, {"chart-daily-balance", "chart-power-flow", "chart-financial"}
    )
    assert texts(page).count("Seasonal comparison requires at least 180 days of simulation data.") == 1

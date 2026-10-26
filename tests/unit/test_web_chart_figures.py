# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each chart the dashboard builds on the server, on the results pages and on the run
comparison page (/history/compare), is drawn from the figure its container carries, or
says why it has none, so its page writes each chart's id once.

components/macros.html's chart_panel writes a panel's id on its container, with the
panel's figure in data-chart-figure, and the container's min-height and the card's heading
are the figure's own height and title. static/js/chart-renderer.js draws each container
that carries a figure, so no script on the page names a chart's id. A chart that applies
to the run but has nothing to draw gets a card that gives the reason, on an element of its
id; a chart that does not apply, a battery's or a heat pump's to a run without one, gets no
card. No other dashboard source, template or script, calls Plotly.

The chart pages share their other parts through components/macros.html too. Each loads
Plotly and chart-renderer.js once, through chart_scripts, the one template that names
them. Each draws its chart tabs through chart_tabs, which selects the first on the server,
so no chart page template writes tab markup.
"""

import dataclasses
import json
import re
import uuid
from collections.abc import Callable, Mapping
from typing import NamedTuple

import pandas as pd
import pytest

pytest.importorskip("flask")

from flask import Flask, url_for

from solar_challenge.battery import BatteryConfig
from solar_challenge.home import SimulationResults
from tests._chart_absences import SANKEY_REASON, monthly_reason, seasonal_reason
from tests._dashboard_sources import dashboard_script_sources, dashboard_template_sources
from tests._finance_builders import (
    make_fleet_results,
    make_home_config,
    make_sim_results,
)
from tests._html_page import chart_figures, element_attributes, element_ids, headings, script_texts, texts_after
from tests._web_app import run_storage_of
from tests._steady_runs import steady_run
from tests._web_runs import store_fleet_run, store_home_run

_CHART_RENDERER_KEY = "static/js/chart-renderer.js"
_PLOTLY_CALL = re.compile(r"\bPlotly\.\w+")
_CHART_PAGE_TEMPLATES = (
    "templates/results/home.html",
    "templates/results/fleet.html",
    "templates/history/compare.html",
)
_TAB_MARKUP = (
    'role="tab"',
    "border-primary-500 text-primary-600 dark:text-primary-400",
    "border-transparent text-slate-500",
)


def _saved_home_run(
    app: Flask, results: SimulationResults, battery_config: BatteryConfig | None = None
) -> str:
    """The id of a new run of *results*, saved to *app*'s store for a make_home_config home with *battery_config*'s battery."""
    run_id = str(uuid.uuid4())
    store_home_run(run_storage_of(app), run_id, make_home_config(battery_config=battery_config), results)
    return run_id


def _page(app: Flask, path: str) -> str:
    """The page *app* answers at *path*, which it must answer 200."""
    response = app.test_client().get(path)

    assert response.status_code == 200
    return response.get_data(as_text=True)


def _home_results_page(
    app: Flask, results: SimulationResults, battery_config: BatteryConfig | None = None
) -> str:
    """The results page of a run of *results*, saved to *app*'s store for a make_home_config home with *battery_config*'s battery."""
    return _page(app, f"/results/{_saved_home_run(app, results, battery_config)}")


def _home_with_a_battery_results_page(app: Flask) -> str:
    """The results page of a saved one-day run of a home with a 5 kWh battery."""
    return _home_results_page(app, make_sim_results(days=1), BatteryConfig(capacity_kwh=5.0))


def _fleet_results_page(app: Flask) -> str:
    """The results page of a saved one-day run of a two-home fleet."""
    run_id = str(uuid.uuid4())
    store_fleet_run(run_storage_of(app), run_id, make_fleet_results(n_homes=2, days=1))
    return _page(app, f"/results/{run_id}")


def _compare_page(app: Flask) -> str:
    """The page comparing two saved one-day home runs."""
    run_ids = [_saved_home_run(app, make_sim_results(days=1)) for _ in range(2)]
    return _page(app, f"/history/compare?ids={','.join(run_ids)}")


class _ChartPage(NamedTuple):
    """A chart page, opened in a test app by *open*, and how many chart tabs it has."""

    open: Callable[[Flask], str]
    tab_count: int


_CHART_PAGES = {
    "home": _ChartPage(_home_with_a_battery_results_page, 4),
    "fleet": _ChartPage(_fleet_results_page, 3),
    "compare": _ChartPage(_compare_page, 2),
}


def _assert_each_panel_is_drawn_or_gives_its_reason(
    page: str, drawn: set[str], absent: Mapping[str, tuple[str, str]] | None = None
) -> None:
    """The chart ids of *page*, the element ids starting 'chart-', are those of the panels *drawn* and *absent*, each on one element.

    Each drawn panel's container carries a Plotly figure, its min-height is the figure's layout height, and the
    figure's layout title is a heading of the page once; no script names a chart id. *absent* gives each absent
    panel's title and reason, which its card reads in that order.
    """
    absences = absent or {}
    figures = chart_figures(page)
    assert {element_id for element_id in element_ids(page) if element_id.startswith("chart-")} == drawn | set(absences)
    assert set(figures) == drawn
    assert sorted(chart_id for chart_id, figure in figures.items() if "data" not in json.loads(figure)) == []
    layouts = {chart_id: json.loads(figure)["layout"] for chart_id, figure in figures.items()}
    styles = {container["id"]: container.get("style") for container in element_attributes(page, "div") if container.get("id") in figures}
    assert styles == {chart_id: f"min-height: {layout['height']}px;" for chart_id, layout in layouts.items()}
    page_headings = headings(page)
    assert {chart_id: page_headings.count(layout["title"]["text"]) for chart_id, layout in layouts.items()} == dict.fromkeys(layouts, 1)
    assert {chart_id: texts_after(page, title, 1) for chart_id, (title, _) in absences.items()} == {
        chart_id: [reason] for chart_id, (_, reason) in absences.items()
    }
    scripts = script_texts(page)
    assert sorted(chart_id for chart_id in drawn | set(absences) if any(chart_id in script for script in scripts)) == []


def test_each_chart_on_the_home_results_page_is_drawn_from_the_figure_its_container_carries(
    app: Flask,
) -> None:
    """A year-long run with a battery and a heat-pump load draws all nine charts."""
    year = make_sim_results()
    results = dataclasses.replace(
        year, heat_pump_load=pd.Series(0.3, index=year.demand.index)
    )

    page = _home_results_page(app, results, BatteryConfig(capacity_kwh=5.0))

    _assert_each_panel_is_drawn_or_gives_its_reason(
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
    _assert_each_panel_is_drawn_or_gives_its_reason(
        _fleet_results_page(app),
        {
            "chart-aggregate-timeline",
            "chart-grid-impact",
            "chart-heatmap",
            "chart-box-plots",
            "chart-distribution-histograms",
        },
    )


def test_each_chart_on_the_compare_page_is_drawn_from_the_figure_its_container_carries(
    app: Flask,
) -> None:
    """Comparing two saved runs draws both charts, the energy totals and the efficiency ratios."""
    _assert_each_panel_is_drawn_or_gives_its_reason(
        _compare_page(app), {"chart-comparison-bar", "chart-comparison-radar"}
    )


def test_a_one_day_home_run_with_no_flow_and_no_battery_gives_the_reason_of_each_chart_it_cannot_draw(
    app: Flask,
) -> None:
    """Its Sankey has no flow to draw, and its monthly and seasonal charts need more days; it has no battery or heat-pump chart."""
    page = _home_results_page(
        app, make_sim_results(self_kwh=0.0, export_kwh=0.0, import_kwh=0.0, days=1)
    )

    _assert_each_panel_is_drawn_or_gives_its_reason(
        page,
        {"chart-daily-balance", "chart-power-flow", "chart-financial"},
        {
            "chart-sankey": ("Energy Flow", SANKEY_REASON),
            "chart-monthly": ("Monthly Energy Summary", monthly_reason(1)),
            "chart-seasonal": ("Seasonal Comparison", seasonal_reason(1)),
        },
    )


def test_a_home_run_of_61_calendar_days_across_the_autumn_fall_back_names_its_61_days_in_each_reason(
    app: Flask,
) -> None:
    """2024-10-01 to 2024-11-30 elapses 61 days and an hour, which a timedelta would count as 62 days."""
    page = _home_results_page(app, steady_run("2024-10-01", "2024-11-30"))

    _assert_each_panel_is_drawn_or_gives_its_reason(
        page,
        {"chart-daily-balance", "chart-power-flow", "chart-financial"},
        {
            "chart-sankey": ("Energy Flow", SANKEY_REASON),
            "chart-monthly": ("Monthly Energy Summary", monthly_reason(61)),
            "chart-seasonal": ("Seasonal Comparison", seasonal_reason(61)),
        },
    )


@pytest.mark.parametrize("chart_page", _CHART_PAGES)
def test_each_chart_page_loads_plotly_and_the_chart_renderer_once(
    app: Flask, chart_page: str
) -> None:
    with app.test_request_context():
        plotly_src = url_for("plotly_js.script")

    sources = [script.get("src") for script in element_attributes(_CHART_PAGES[chart_page].open(app), "script")]

    assert (sources.count(plotly_src), sources.count("/static/js/chart-renderer.js")) == (1, 1)


def test_only_components_macros_html_names_the_chart_scripts() -> None:
    naming = sorted(
        template
        for template, source in dashboard_template_sources().items()
        if "plotly_js.script" in source or "js/chart-renderer.js" in source
    )

    assert naming == ["templates/components/macros.html"], (
        "Only components/macros.html's chart_scripts writes the tags that load Plotly and"
        " chart-renderer.js; a chart page calls chart_scripts()"
    )


@pytest.mark.parametrize("chart_page", _CHART_PAGES)
def test_each_chart_pages_tabs_are_tabs_whose_selection_the_server_draws(
    app: Flask, chart_page: str
) -> None:
    opened = _CHART_PAGES[chart_page]
    tabs = [
        button
        for button in element_attributes(opened.open(app), "button")
        if button.get("role") == "tab"
    ]

    assert [tab.get("aria-selected") for tab in tabs] == ["true"] + ["false"] * (opened.tab_count - 1)


def test_no_chart_page_template_writes_tab_markup() -> None:
    sources = dashboard_template_sources()

    written = {
        template: [markup for markup in _TAB_MARKUP if markup in sources[template]]
        for template in _CHART_PAGE_TEMPLATES
    }

    assert written == dict.fromkeys(_CHART_PAGE_TEMPLATES, []), (
        "A chart page draws its tabs through components/macros.html's chart_tabs, the one"
        " home of the tab markup"
    )


def test_no_dashboard_source_but_chart_renderer_js_calls_plotly() -> None:
    sources = {**dashboard_template_sources(), **dashboard_script_sources()}
    assert _PLOTLY_CALL.search(sources.get(_CHART_RENDERER_KEY, "")), (
        f"read no Plotly call from {_CHART_RENDERER_KEY}, so this guard would pass vacuously"
    )

    calls = {
        path: found
        for path, source in sources.items()
        if path != _CHART_RENDERER_KEY and (found := sorted(set(_PLOTLY_CALL.findall(source))))
    }

    listing = "".join(f"\n  {path}: {' '.join(found)}" for path, found in calls.items())
    assert calls == {}, (
        f"These dashboard sources call Plotly themselves:{listing}\n"
        f"Only {_CHART_RENDERER_KEY} calls Plotly, so that every chart is drawn in the theme's "
        "colours, waits for its hidden tab to be shown and reports a failed draw. Draw the chart "
        "through components/macros.html's chart_panel, whose container chart-renderer.js draws."
    )

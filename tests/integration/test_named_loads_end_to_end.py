# SPDX-License-Identifier: AGPL-3.0-or-later
"""B8 of docs/prds/load-composition-and-calendar-days.md: a home's named loads, end to end.

`home run --report --output` of a home with a heat pump and an EV prints a Demand by load table
whose rows are each load, summing to the run's demand, and writes each load's column. The
dashboard's results page of a stored heat-pump run draws the demand-by-load panel and the heat
pump's profile panel, and that of a run whose demand is the household's alone draws neither.
The page tests import the web package when they run, so the CLI test needs no web extra.
"""

import uuid
from contextlib import ExitStack
from pathlib import Path

import pandas as pd
import pytest

from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.weather import WeatherCache
from tests._home_run_demand import home_run
from tests._html_page import chart_figures, element_ids
from tests._plotly_figure import traces
from tests._summary_report_tables import cells, energy_totals_demand_kwh, table_under
from tests._synthetic_weather import synthetic_tmy, weather_for
from tests._web_app import app_builder, run_storage_of

_LOAD_PANEL_IDS = {"chart-demand-by-load", "chart-load-profile-heat-pump"}

_OFF_PEAK_EV = {
    "charger_type": "7kW",
    "arrival_hour": 18,
    "departure_hour": 7,
    "required_charge_kwh": 35,
    "smart_charging_mode": "off_peak",
}


def test_home_run_report_lists_each_load_summing_to_the_demand(tmp_path: Path, weather_cache: WeatherCache) -> None:
    run = home_run(
        tmp_path,
        weather_cache,
        ev_block=_OFF_PEAK_EV,
        heat_pump_block={"heat_pump_type": "ASHP"},
        start="2024-03-30",
        end="2024-04-01",
    )
    lines = run.report.splitlines()

    _header, *rows = table_under(lines, "## Demand by load")

    assert [cells(row)[0] for row in rows] == ["Household", "Heat pump", "EV charging"]
    assert sum(float(cells(row)[1]) for row in rows) == pytest.approx(energy_totals_demand_kwh(lines), abs=0.1)
    assert len(run.frame) == 4_260
    assert {"heat_pump_load_kw", "ev_load_kw"} <= set(run.frame.columns)


def _stored_run_results_page(
    closes_at_teardown: ExitStack, tmp_path: Path, heat_pump_config: HeatPumpConfig | None
) -> str:
    """The results page of a stored simulate_home run, on 30 March 2024, of a Bristol home with *heat_pump_config* as its heat pump.

    The home has 4 kW of PV and a deterministic 3,400 kWh load; synthetic_tmy() is its weather,
    whose whole year of hourly temperature a heat pump's heat demand is shared out over.
    """
    pytest.importorskip("flask")
    from tests._web_runs import store_home_run

    home = HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False),
        heat_pump_config=heat_pump_config,
    )
    day = pd.Timestamp("2024-03-30")
    results = simulate_home(home, day, day, weather=weather_for(home, synthetic_tmy()))
    app = app_builder(closes_at_teardown)(tmp_path)
    run_id = str(uuid.uuid4())
    store_home_run(run_storage_of(app), run_id, home, results)

    response = app.test_client().get(f"/results/{run_id}")

    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_results_page_of_a_stored_heat_pump_run_draws_the_demand_by_load_and_heat_pump_profile_panels(
    closes_at_teardown: ExitStack, tmp_path: Path
) -> None:
    figures = chart_figures(_stored_run_results_page(closes_at_teardown, tmp_path, HeatPumpConfig.default_ashp()))

    assert _LOAD_PANEL_IDS <= set(figures)
    assert traces(figures["chart-demand-by-load"])[0]["labels"] == ["Household", "Heat pump"]


def test_results_page_of_a_plain_run_draws_neither(closes_at_teardown: ExitStack, tmp_path: Path) -> None:
    page = _stored_run_results_page(closes_at_teardown, tmp_path, heat_pump_config=None)

    assert _LOAD_PANEL_IDS & element_ids(page) == set()

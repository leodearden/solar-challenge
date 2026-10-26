# SPDX-License-Identifier: AGPL-3.0-or-later
"""The results page of a home run lists its heat-pump charts exactly when the run carries a heat-pump load.

home_results_tabs lists the two panels heat_pump_analysis returns, the heat pump's share of
demand and its load profile, only for a run with a heat-pump load, so the page draws each
one's figure in a container of its own id; a run without one has no card for either.
"""

import dataclasses
import uuid
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("flask")

from solar_challenge.home import SimulationResults
from tests._finance_builders import make_home_config, make_sim_results
from tests._html_page import chart_figures, element_ids
from tests._web_app import build_test_app, run_storage_of
from tests._web_runs import store_home_run

_HEAT_PUMP_CHART_IDS = {"chart-hp-load-share", "chart-hp-load-profile"}


def _home_results_page(tmp_path: Path, results: SimulationResults) -> str:
    """The results page of a saved run of *results*, for a make_home_config home."""
    app = build_test_app(tmp_path)
    run_id = str(uuid.uuid4())
    store_home_run(run_storage_of(app), run_id, make_home_config(), results)

    response = app.test_client().get(f"/results/{run_id}")

    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_home_results_page_of_a_run_with_a_heat_pump_draws_each_heat_pump_chart_in_its_container(
    tmp_path: Path,
) -> None:
    one_day = make_sim_results(days=1)
    results = dataclasses.replace(one_day, heat_pump_load=pd.Series(0.3, index=one_day.demand.index))

    figures = chart_figures(_home_results_page(tmp_path, results))

    assert _HEAT_PUMP_CHART_IDS <= set(figures)


def test_home_results_page_of_a_run_without_a_heat_pump_has_no_heat_pump_chart(tmp_path: Path) -> None:
    assert _HEAT_PUMP_CHART_IDS & element_ids(_home_results_page(tmp_path, make_sim_results(days=1))) == set()

# SPDX-License-Identifier: AGPL-3.0-or-later
"""The results page of a home run that carries a heat-pump load has a container for each heat-pump chart.

heat_pump_analysis returns each heat-pump figure in a field of a HeatPumpCharts, which
results/home.html reads by name, and the page gives each figure a container of its own id.
A name the template reads that HeatPumpCharts has no field for is Undefined, which
chart_panel refuses, so the page fails to render, naming that name.
"""

import dataclasses
import uuid
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("flask")

from tests._finance_builders import make_home_config, make_sim_results
from tests._html_page import element_ids
from tests._web_app import build_test_app, run_storage_of
from tests._web_runs import store_home_run


def test_home_results_page_of_a_run_with_a_heat_pump_has_a_container_for_each_heat_pump_chart(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    one_day = make_sim_results(days=1)
    results = dataclasses.replace(one_day, heat_pump_load=pd.Series(0.3, index=one_day.demand.index))
    run_id = str(uuid.uuid4())
    store_home_run(run_storage_of(app), run_id, make_home_config(), results)

    response = app.test_client().get(f"/results/home/{run_id}")

    assert response.status_code == 200
    assert {"chart-hp-load-share", "chart-hp-load-profile"} <= element_ids(
        response.get_data(as_text=True)
    )

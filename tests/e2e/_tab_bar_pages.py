# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pages whose tab bars components/macros.html's tab_bar draws, as pytest params of TabBarPage, for the e2e tests every tab bar must pass."""

from collections.abc import Callable
from typing import NamedTuple

import pytest


class TabBarPage(NamedTuple):
    """A page with a tab bar: its path, given the test's request, through which a page of stored runs requests the fixture seeding them, and its tabs' names, the opening tab first."""

    path_of: Callable[[pytest.FixtureRequest], str]
    tab_names: tuple[str, ...]


def _simulate_home_path(request: pytest.FixtureRequest) -> str:
    return "/simulate/home"


def _results_home_path(request: pytest.FixtureRequest) -> str:
    run_id, _ = request.getfixturevalue("seeded_home_run")
    return f"/results/home/{run_id}"


def _results_fleet_path(request: pytest.FixtureRequest) -> str:
    run_id, _ = request.getfixturevalue("seeded_fleet_run")
    return f"/results/fleet/{run_id}"


def _history_compare_path(request: pytest.FixtureRequest) -> str:
    runs = request.getfixturevalue("seeded_home_runs_pair")
    return "/history/compare?ids=" + ",".join(run_id for run_id, _ in runs)


PAGES_WITH_TAB_BARS = [
    pytest.param(
        TabBarPage(_simulate_home_path, ("PV", "Battery", "Load", "Heat Pump", "Tariff", "Location", "Period")),
        id="simulate-home",
    ),
    pytest.param(
        TabBarPage(_results_home_path, ("Overview", "Power Flow", "Battery & Finance", "Analysis")),
        id="results-home",
    ),
    pytest.param(
        TabBarPage(_results_fleet_path, ("Aggregate", "Per-Home", "Distributions")),
        id="results-fleet",
    ),
    pytest.param(
        TabBarPage(_history_compare_path, ("Energy Totals", "Efficiency Ratios")),
        id="history-compare",
    ),
]

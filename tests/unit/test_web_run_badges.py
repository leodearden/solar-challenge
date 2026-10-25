# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the one home of the run badges: components/macros.html draws each run status and
run type in that value's colours, gives every status and type a run can be stored with
colours of its own, and every page draws its badges through those macros.

A bound badge takes its colours only once Alpine evaluates it, so tests/e2e checks that
each one, in a browser, carries the classes the server-drawn badge has for the same value.
"""

from collections.abc import Mapping
from typing import Any

import pytest

pytest.importorskip("flask")
from flask import Flask

from solar_challenge.web.storage import RUN_STATUSES, RunStatus, RunStorage
from solar_challenge.web.stored_runs import RUN_TYPES, RunType
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._html_page import element_attributes, texts
from tests._server_drawn_badges import server_drawn_badge, server_drawn_classes
from tests._web_runs import store_fleet_run, store_home_run

_BADGE = {"inline-flex", "items-center", "px-2.5", "py-0.5", "rounded-full", "text-xs", "font-medium"}
_NEUTRAL = {"bg-slate-100", "text-slate-800", "dark:bg-slate-700", "dark:text-slate-300"}


def _colours(palette: str) -> set[str]:
    """The classes that colour a badge in *palette*, in light and dark mode."""
    return {
        f"bg-{palette}-100",
        f"text-{palette}-800",
        f"dark:bg-{palette}-900/30",
        f"dark:text-{palette}-400",
    }


def _spans(app: Flask, path: str) -> list[Mapping[str, str | None]]:
    """The attributes of each span of the page *app* serves at *path*, in document order."""
    response = app.test_client().get(path)
    assert response.status_code == 200, f"GET {path} answered {response.status_code}"
    return element_attributes(response.get_data(as_text=True), "span")


def _save_home_run(storage: RunStorage, run_id: str, status: RunStatus = "completed") -> None:
    """Save a 1-day home run under *run_id* to *storage*, with *status*."""
    store_home_run(storage, run_id, make_home_config(), make_sim_results(days=1), status=status)


@pytest.mark.parametrize(
    ("status", "colours"),
    [
        pytest.param("running", _colours("amber"), id="running"),
        pytest.param("completed", _colours("green"), id="completed"),
        pytest.param("failed", _colours("red"), id="failed"),
        pytest.param("pending", _NEUTRAL, id="pending"),
        pytest.param("queued", _NEUTRAL, id="a status with no colours of its own"),
    ],
)
def test_a_run_status_badge_shows_the_status_in_its_colours(
    macros: Any, status: str, colours: set[str]
) -> None:
    badge = macros.run_status_badge(status)

    assert texts(str(badge)) == [status]
    assert server_drawn_classes(badge) == _BADGE | colours


@pytest.mark.parametrize("status", RUN_STATUSES)
def test_each_status_a_run_is_stored_with_has_colours_of_its_own(
    macros: Any, status: RunStatus
) -> None:
    assert server_drawn_classes(macros.run_status_badge(status)) != _BADGE | _NEUTRAL, (
        f"run status {status!r} is drawn neutral; give it colours in"
        " components/macros.html's _run_status_badge_classes"
    )


@pytest.mark.parametrize(
    ("run_type", "colours"),
    [
        pytest.param("home", _colours("blue"), id="home"),
        pytest.param("fleet", _colours("green"), id="fleet"),
        pytest.param("batch", _NEUTRAL, id="a type with no colours of its own"),
    ],
)
def test_a_run_type_badge_shows_the_type_in_its_colours(
    macros: Any, run_type: str, colours: set[str]
) -> None:
    badge = macros.run_type_badge(run_type)

    assert texts(str(badge)) == [run_type]
    assert server_drawn_classes(badge) == _BADGE | colours


@pytest.mark.parametrize("run_type", RUN_TYPES)
def test_each_type_a_run_is_stored_with_has_colours_of_its_own(
    macros: Any, run_type: RunType
) -> None:
    assert server_drawn_classes(macros.run_type_badge(run_type)) != _BADGE | _NEUTRAL, (
        f"run type {run_type!r} is drawn neutral; give it colours in"
        " components/macros.html's _run_type_badge_classes"
    )


def test_the_dashboard_draws_each_recent_runs_status_with_run_status_badge(
    app: Flask, storage: RunStorage, macros: Any
) -> None:
    for status in RUN_STATUSES:
        _save_home_run(storage, f"{status}-run", status)

    spans = _spans(app, "/")

    assert {
        status: spans.count(server_drawn_badge(macros.run_status_badge(status)))
        for status in RUN_STATUSES
    } == dict.fromkeys(RUN_STATUSES, 1)


def test_the_compare_page_draws_each_runs_type_with_run_type_badge(
    app: Flask, storage: RunStorage, macros: Any
) -> None:
    _save_home_run(storage, "cmp-home")
    store_fleet_run(storage, "cmp-fleet", make_fleet_results(n_homes=2, days=1))

    spans = _spans(app, "/history/compare?ids=cmp-home,cmp-fleet")

    assert {
        run_type: spans.count(server_drawn_badge(macros.run_type_badge(run_type)))
        for run_type in ("home", "fleet")
    } == {"home": 1, "fleet": 1}


def test_run_history_draws_each_runs_status_and_type_with_the_bound_badges_in_the_table_and_the_cards(
    app: Flask, macros: Any
) -> None:
    spans = _spans(app, "/history/runs")

    assert {
        "status": spans.count(server_drawn_badge(macros.bound_run_status_badge("run.status"))),
        "type": spans.count(server_drawn_badge(macros.bound_run_type_badge("run.type"))),
    } == {"status": 2, "type": 2}


def test_the_sweep_page_draws_each_points_status_with_the_bound_run_status_badge(
    app: Flask, macros: Any
) -> None:
    spans = _spans(app, "/scenarios/sweep")

    assert spans.count(server_drawn_badge(macros.bound_run_status_badge("row.status"))) == 1

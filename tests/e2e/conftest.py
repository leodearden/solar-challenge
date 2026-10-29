"""Shared fixtures for Playwright e2e tests.

Provides a live Flask server running in a background thread,
configures Playwright's base_url so tests can use relative paths, and
gives tests the server's dashboard macros, to compare a page with
what a macro draws. The live server's jobs simulate on the cache
live_server_weather returns, synthetic_tmy() at each location preset
the dashboard offers; a test module chooses other weather by
overriding live_server_weather to return a WeatherCache of its own.

Includes data-seeding fixtures, which save completed runs through the
live server's own RunStorage, for tests that need pre-existing
simulation runs (dashboard, results pages, history interactions,
compare page), and home_preset_saved_under_a_builtin_name, which writes
a saved home preset under a built-in preset's name straight into the
live server's database.
Also stubs the Run History page's runs-list API for tests that need it
empty, unanswered or listing a run of each badge, and collects the
errors a page reports. release_held_simulations holds the live server's
jobs inside their simulations until the test releases them, and
job_streams_time_out_after_a_second ends each of the live server's job
progress streams about a second after it opens.

Every browser context a test opens refuses each request to another origin
than the live server's, as if the network were down, and the test errors at
teardown, naming each refused URL.

A test that fails after Chromium failed one of its requests with
net::ERR_NETWORK_CHANGED runs once more; docs/e2e-network-change-reruns.md
says why.

It imports playwright's and pytest-playwright's types for annotations only,
so nothing from the e2e extra when it loads: tests/unit/test_e2e_job_wait.py
and tests/unit/test_e2e_network_change_reruns.py run copies of this module
in the verify environment, which lacks that extra.
"""

from __future__ import annotations

import functools
import json
import re
import threading
import uuid
from collections.abc import Callable, Generator, Iterator
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import pandas as pd
import pytest
pytest.importorskip("werkzeug")
from flask import Flask
from werkzeug.serving import make_server

from solar_challenge.battery import BatteryConfig
from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.weather import CACHE_DIR_VARIABLE, WeatherCache
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.request_boundary import LOCATION_PRESETS
from solar_challenge.web.shared import get_job_manager, get_job_stream_policy
from solar_challenge.web.storage import RunStorage

from tests._config_preset_rows import insert_saved_home_preset
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._server_drawn_badges import dashboard_macros_of
from tests._synthetic_weather import synthetic_tmy
from tests._web_app import build_test_app, database_of, run_storage_of
from tests._web_runs import store_fleet_run, store_home_run

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Route
    from pytest_playwright import CreateContextCallback


# ---------------------------------------------------------------------------
# Live server
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def live_server_weather(tmp_path_factory: pytest.TempPathFactory) -> WeatherCache:
    """The weather cache the live server's jobs simulate on: synthetic_tmy() at each location preset.

    The TMY is a whole year, which a heat pump's job needs. A test module overrides this fixture to return a
    WeatherCache of its own.
    """
    cache = WeatherCache(cache_dir=tmp_path_factory.mktemp("e2e-weather"))
    tmy = synthetic_tmy()
    for location in LOCATION_PRESETS.values():
        cache.put(tmy, "tmy", location)
    return cache


@pytest.fixture(scope="session")
def _e2e_app(tmp_path_factory: pytest.TempPathFactory, live_server_weather: WeatherCache) -> Flask:
    """The Flask app the live server serves, its jobs simulating on live_server_weather.

    create_app binds default_weather() as it builds the app, so CACHE_DIR_VARIABLE names that cache for the build
    alone, and each test's offline window keeps its own.
    """
    data_dir = tmp_path_factory.mktemp("e2e")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(CACHE_DIR_VARIABLE, str(live_server_weather.cache_dir))
        return build_test_app(data_dir)


@pytest.fixture(scope="session")
def _e2e_storage(_e2e_app: Flask) -> RunStorage:
    """The RunStorage holding the runs the live server's pages show; each seeding fixture saves its runs through it.

    create_app built its database schema, so a fixture can seed it before the server starts.
    """
    return run_storage_of(_e2e_app)


@pytest.fixture(scope="session")
def _e2e_job_manager(_e2e_app: Flask) -> Iterator[JobManager]:
    """The JobManager that runs the live server's simulation jobs.

    It lives for the whole session: the per-test drain in tests/conftest.py
    leaves it alone, _jobs_finish_within_their_test waits for each test's jobs,
    and this fixture shuts it down at session end.
    """
    with _e2e_app.app_context():
        manager = get_job_manager()
    yield manager
    manager.shutdown(wait=True)


@pytest.fixture(scope="session")
def live_server(_e2e_app: Flask, _e2e_job_manager: JobManager) -> Iterator[str]:
    """Start the Flask app on a random port in a daemon thread.

    Each connection is served on its own thread so that open SSE progress
    streams do not stall other requests.

    Yields the base URL (e.g. ``http://127.0.0.1:54321``).  It requests
    _e2e_job_manager so that pytest stops this server before shutting down
    the manager its requests submit jobs to.
    """
    with make_server("127.0.0.1", 0, _e2e_app, threaded=True) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        yield f"http://127.0.0.1:{server.port}"

        server.shutdown()
        thread.join()


_JOBS_FINISH_TIMEOUT_S = 120


@pytest.fixture(autouse=True)
def _jobs_finish_within_their_test(_e2e_job_manager: JobManager) -> Iterator[None]:
    """At teardown, wait until the live server has no job queued or running.

    The jobs run in threads of this pytest process, and jobs left running slow the next test's browser work.
    """
    yield
    if not _e2e_job_manager.wait_until_idle(timeout=_JOBS_FINISH_TIMEOUT_S):
        pytest.fail(
            f"jobs submitted during this test were still running on the live server "
            f"{_JOBS_FINISH_TIMEOUT_S} s after it ended"
        )


@pytest.fixture
def release_held_simulations(_e2e_app: Flask, _e2e_storage: RunStorage) -> Iterator[Callable[[], None]]:
    """Hold each job the live server runs during the test inside its simulation until the test calls the function this yields.

    The jobs run on a JobManager of their own, two at a time as on the session's.
    Once released, each simulates a day in which its home self-consumes 24 kWh,
    exports 48 kWh and imports 12 kWh. Teardown releases them, waits for them
    and puts the session's JobManager back.
    """
    released = threading.Event()

    def held_simulation(config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
        released.wait()
        return make_sim_results(self_kwh=24.0, export_kwh=48.0, import_kwh=12.0, days=1)

    session_job_manager = _e2e_app.extensions["job_manager"]
    held_job_manager = JobManager(_e2e_storage, simulate_home=held_simulation)
    _e2e_app.extensions["job_manager"] = held_job_manager
    yield released.set
    released.set()
    finished = held_job_manager.wait_until_idle(timeout=_JOBS_FINISH_TIMEOUT_S)
    _e2e_app.extensions["job_manager"] = session_job_manager
    if not finished:
        pytest.fail(
            f"jobs held by release_held_simulations were still running on the live server "
            f"{_JOBS_FINISH_TIMEOUT_S} s after it released them"
        )


@pytest.fixture
def job_streams_time_out_after_a_second(_e2e_app: Flask) -> Iterator[None]:
    """Serve the live server's job progress streams under the session's policy with a one-second limit, polled every quarter second.

    A stream checks its limit as it polls, so each stream of a running job ends with its timeout 1 to 1.25 s after it opens.
    Teardown puts the session's policy back.
    """
    with _e2e_app.app_context():
        session_policy = get_job_stream_policy()
    _e2e_app.extensions["job_stream_policy"] = replace(session_policy, limit_seconds=1.0, heartbeat_seconds=0.25)
    yield
    _e2e_app.extensions["job_stream_policy"] = session_policy


@pytest.fixture(scope="session")
def base_url(live_server):
    """Override pytest-playwright's base_url with our live server."""
    return live_server


@pytest.fixture(scope="session")
def dashboard_macros(_e2e_app: Flask) -> Any:
    """The public macros of the live server's components/macros.html, as callables that return their markup.

    A test compares what a page shows with what a macro draws for the same value.
    """
    return dashboard_macros_of(_e2e_app)


# ---------------------------------------------------------------------------
# Requests to other origins
# ---------------------------------------------------------------------------


def _urls_outside(origin: str) -> re.Pattern[str]:
    """A pattern matching every URL outside *origin*.

    Playwright matches a pattern in its driver; a predicate would stop every request the browser makes to ask this process.
    """
    return re.compile(f"^(?!{re.escape(origin)}/)")


@pytest.fixture
def new_context(
    new_context: CreateContextCallback, live_server: str, request: pytest.FixtureRequest
) -> Iterator[Callable[..., BrowserContext]]:
    """Wrap pytest-playwright's new_context so that each browser context it opens refuses every request to another origin than the live server's, as if the network were down.

    It opens the context fixture's browser context, and so the page fixture's, as well as each one a test opens itself.
    At teardown the test errors, naming each URL refused.
    """
    refused: list[str] = []

    def _refuse(route: Route) -> None:
        refused.append(route.request.url)
        route.abort("internetdisconnected")

    def new_context_refusing_other_origins(**kwargs: Any) -> BrowserContext:
        context = new_context(**kwargs)
        context.route(_urls_outside(live_server), _refuse)
        return context

    yield new_context_refusing_other_origins
    if refused:
        pytest.fail(
            f"{request.node.nodeid} requested other origins ({', '.join(dict.fromkeys(refused))}); "
            "an e2e test's browser reaches only the live server: serve each file a page loads from the app, "
            "as tests/unit/test_web_page_scripts.py describes for scripts",
            pytrace=False,
        )


# ---------------------------------------------------------------------------
# Seeded data fixtures
# ---------------------------------------------------------------------------


def _save_seeded_home_run(
    storage: RunStorage, run_id: str, run_name: str, results: SimulationResults
) -> tuple[str, str]:
    """Save *results* as a completed run named *run_name*, of a 5 kWh battery home of that name, as a finished home job saves its run.

    The battery gives the run's results page its battery stat cards. Returns (run_id, run_name).
    """
    home = replace(make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0)), name=run_name)
    store_home_run(storage, run_id, home, results, name=run_name)
    return run_id, run_name


@pytest.fixture(scope="session")
def seeded_home_run(_e2e_storage: RunStorage) -> tuple[str, str]:
    """Save a completed 1-day home run through RunStorage. Returns (run_id, run_name).

    Its results are make_sim_results' constant-power series, so no simulation runs and no service is reached.
    """
    return _save_seeded_home_run(
        _e2e_storage,
        "seed-home-001",
        "Seeded Home Alpha",
        make_sim_results(self_kwh=60.0, export_kwh=40.0, import_kwh=20.0, days=1),
    )


@pytest.fixture(scope="session")
def seeded_multi_day_home_run(_e2e_storage: RunStorage) -> tuple[str, str]:
    """Save a completed 3-day home run through RunStorage, for tests that need a run whose charts span several days. Returns (run_id, run_name).

    Its results are make_sim_results' constant-power series: each day 30 kWh is self-consumed, 20 kWh exported and 10 kWh imported.
    """
    return _save_seeded_home_run(
        _e2e_storage,
        "seed-home-3day-001",
        "Seeded Home Three Days",
        make_sim_results(self_kwh=90.0, export_kwh=60.0, import_kwh=30.0, days=3),
    )


@pytest.fixture(scope="session")
def seeded_home_runs_pair(_e2e_storage: RunStorage) -> list[tuple[str, str]]:
    """Save 2 completed 1-day home runs through RunStorage, the second importing more from the grid.

    Returns [(id1, name1), (id2, name2)].
    """
    return [
        _save_seeded_home_run(
            _e2e_storage,
            "seed-cmp-001",
            "Compare Run A",
            make_sim_results(self_kwh=70.0, export_kwh=50.0, import_kwh=20.0, days=1),
        ),
        _save_seeded_home_run(
            _e2e_storage,
            "seed-cmp-002",
            "Compare Run B",
            make_sim_results(self_kwh=50.0, export_kwh=30.0, import_kwh=50.0, days=1),
        ),
    ]


@pytest.fixture(scope="session")
def seeded_fleet_run(_e2e_storage: RunStorage) -> tuple[str, str]:
    """Save a completed 2-home, 1-day fleet run through RunStorage. Returns (run_id, run_name).

    Its homes' results are make_fleet_results' constant-power series, so no simulation runs and no service is reached.
    """
    run_id, run_name = "seed-fleet-001", "Seeded Fleet Alpha"
    fleet = make_fleet_results(n_homes=2, self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)
    store_fleet_run(_e2e_storage, run_id, fleet, name=run_name)
    return run_id, run_name


@pytest.fixture
def newest_home_run(_e2e_storage: RunStorage) -> tuple[str, str]:
    """Save a completed 1-day home run as the test starts, so the run heads the dashboard's Recent Runs. Returns (run_id, run_name).

    The dashboard lists only the 10 newest runs, and the session's other tests save runs of their own.
    """
    suffix = uuid.uuid4().hex[:8]
    return _save_seeded_home_run(
        _e2e_storage,
        f"seed-newest-{suffix}",
        f"Newest Home {suffix}",
        make_sim_results(self_kwh=60.0, export_kwh=40.0, import_kwh=20.0, days=1),
    )


@pytest.fixture
def home_preset_saved_under_a_builtin_name(_e2e_app: Flask) -> Iterator[dict[str, object]]:
    """Write a saved home preset named 'Small Urban', a built-in preset's name, into the live server's database. Yields its config.

    Its values are unlike the built-in one's, so applying the wrong preset shows. The session's
    tests share the database, so the row is deleted at teardown.
    """
    config: dict[str, object] = {"pv_kw": 9.5, "battery_kwh": 7.0, "consumption_kwh": 6000}
    database = database_of(_e2e_app)
    preset_id = insert_saved_home_preset(database, "Small Urban", json.dumps(config))
    yield config
    with database.transaction() as conn:
        conn.execute("DELETE FROM config_presets WHERE id = ?", (preset_id,))


# ---------------------------------------------------------------------------
# Run History API stubs
# ---------------------------------------------------------------------------


def _is_runs_list_request(url: str) -> bool:
    return urlsplit(url).path == "/api/history/runs"


@pytest.fixture
def runs_api_returns_no_runs(page, live_server: str) -> None:
    """Answer the Run History page's runs-list requests as the live API answers a search no run matches."""
    no_runs_response = page.request.get(
        live_server + "/api/history/runs",
        params={"q": uuid.uuid4().hex},
        fail_on_status_code=True,
    ).json()
    page.route(
        _is_runs_list_request,
        lambda route: route.fulfill(json=no_runs_response),
    )


@pytest.fixture
def runs_api_returns_a_run_of_each_badge(
    page, live_server: str, seeded_home_run: tuple[str, str]
) -> list[tuple[str, str]]:
    """Answer the Run History page's runs-list requests with one run per (type, status) pair it returns, each a copy of the seeded home run as the live API lists it.

    The pairs name every run type and every status a run is stored with, and 'queued', a status with no badge colours of its own.
    """
    badges = [("home", "running"), ("fleet", "completed"), ("fleet", "failed"), ("home", "queued")]
    listed = page.request.get(
        live_server + "/api/history/runs",
        params={"q": seeded_home_run[1]},
        fail_on_status_code=True,
    ).json()
    runs = [
        {
            **listed["runs"][0],
            "id": f"badge-run-{n}",
            "name": f"Badge Run {n}",
            "type": run_type,
            "status": status,
        }
        for n, (run_type, status) in enumerate(badges, start=1)
    ]
    page.route(
        _is_runs_list_request,
        lambda route: route.fulfill(json={**listed, "runs": runs}),
    )
    return badges


@pytest.fixture
def runs_api_never_answers(page) -> Iterator[None]:
    """Hold the Run History page's runs-list requests unanswered for the whole test, then abort them."""
    held_requests = []
    page.route(_is_runs_list_request, lambda route: held_requests.append(route))
    yield
    assert held_requests, "the page made no runs-list request for runs_api_never_answers to hold"
    for route in held_requests:
        route.abort()


# ---------------------------------------------------------------------------
# Page errors
# ---------------------------------------------------------------------------


@pytest.fixture
def page_errors(page) -> list[str]:
    """The text of each console error the page logs and each uncaught exception it throws during the test.

    Playwright reports an uncaught exception, such as an Alpine expression error, only as a pageerror.
    """
    errors: list[str] = []

    def _collect_console_error(message) -> None:
        if message.type == "error":
            errors.append(message.text)

    page.on("console", _collect_console_error)
    page.on("pageerror", lambda error: errors.append(str(error)))
    return errors


# ---------------------------------------------------------------------------
# Requests lost to host network changes
# ---------------------------------------------------------------------------

_NETWORK_CHANGED = "net::ERR_NETWORK_CHANGED"
_RERUNS_AFTER_A_NETWORK_CHANGE = 1
_REQUESTS_LOST_TO_NETWORK_CHANGES = pytest.StashKey[list[str]]()


@pytest.fixture(autouse=True)
def _record_requests_lost_to_network_changes(request: pytest.FixtureRequest) -> None:
    """Record, as "METHOD URL", each request the test's browser context fails with net::ERR_NETWORK_CHANGED during this attempt.

    Each attempt's record starts empty before its context starts, so an attempt
    whose context fails to start has lost nothing. It starts no context for a test that uses none.
    """
    lost: list[str] = []
    request.node.stash[_REQUESTS_LOST_TO_NETWORK_CHANGES] = lost
    if "context" not in request.fixturenames:
        return

    def _record_if_lost_to_a_network_change(failed_request: Any) -> None:
        if failed_request.failure == _NETWORK_CHANGED:
            lost.append(f"{failed_request.method} {failed_request.url}")

    request.getfixturevalue("context").on("requestfailed", _record_if_lost_to_a_network_change)


def _lost_a_request_to_a_network_change(item: pytest.Item) -> bool:
    """Whether the test's browser context failed a request with net::ERR_NETWORK_CHANGED during its latest attempt."""
    return bool(item.stash.get(_REQUESTS_LOST_TO_NETWORK_CHANGES, []))


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Run each test under this directory once more if it fails after its browser lost a request to a network change.

    The hook is given every test in the session, so it leaves the tests outside this directory alone.
    """
    for item in items:
        if item.path.is_relative_to(Path(__file__).parent):
            item.add_marker(
                pytest.mark.flaky(
                    reruns=_RERUNS_AFTER_A_NETWORK_CHANGE,
                    condition=functools.partial(_lost_a_request_to_a_network_change, item),
                )
            )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Add to the report of a failure a section that lists the requests this attempt lost to network changes, if any."""
    report = yield
    lost = item.stash.get(_REQUESTS_LOST_TO_NETWORK_CHANGES, [])
    if report.failed and lost:
        report.sections.append(
            (
                f"requests Chromium failed with {_NETWORK_CHANGED}",
                "\n".join([*lost, "docs/e2e-network-change-reruns.md says how a host network change fails a request"]),
            )
        )
    return report

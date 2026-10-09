"""Shared fixtures for Playwright e2e tests.

Provides a live Flask server running in a background thread and
configures Playwright's base_url so tests can use relative paths.

Includes data-seeding fixtures, which save completed runs through the
live server's own RunStorage, for tests that need pre-existing
simulation runs (dashboard, results pages, history interactions,
compare page), and home_preset_saved_under_a_builtin_name, which writes
a saved home preset under a built-in preset's name straight into the
live server's database.
Also stubs the Run History page's runs-list API for tests that need it
empty or unanswered, and collects the errors a page reports.

A test that fails after Chromium failed one of its requests with
net::ERR_NETWORK_CHANGED runs once more; docs/e2e-network-change-reruns.md
says why.

It imports nothing from playwright: tests/unit/test_e2e_job_wait.py and
tests/unit/test_e2e_network_change_reruns.py run copies of this module in
the verify environment, which lacks the e2e extra.
"""

import functools
import json
import socket
import sqlite3
import threading
import uuid
from collections.abc import Generator, Iterator
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
pytest.importorskip("werkzeug")
from flask import Flask
from werkzeug.serving import make_server

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import calculate_fleet_summary
from solar_challenge.home import SimulationResults, calculate_summary
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.shared import get_job_manager, get_storage
from solar_challenge.web.storage import RunStorage

from tests._config_preset_rows import insert_saved_home_preset
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._web_app import build_test_app


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Live server
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _e2e_app(tmp_path_factory: pytest.TempPathFactory) -> Flask:
    """The Flask app the live server serves."""
    return build_test_app(tmp_path_factory.mktemp("e2e"))


@pytest.fixture(scope="session")
def _e2e_storage(_e2e_app: Flask) -> RunStorage:
    """The RunStorage holding the runs the live server's pages show; each seeding fixture saves its runs through it.

    create_app built its database schema, so a fixture can seed it before the server starts.
    """
    with _e2e_app.app_context():
        return get_storage()


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
    port = _find_free_port()
    server = make_server("127.0.0.1", port, _e2e_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}"

    server.shutdown()


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


@pytest.fixture(scope="session")
def base_url(live_server):
    """Override pytest-playwright's base_url with our live server."""
    return live_server


# ---------------------------------------------------------------------------
# Seeded data fixtures
# ---------------------------------------------------------------------------


def _save_seeded_home_run(
    storage: RunStorage, run_id: str, run_name: str, results: SimulationResults
) -> tuple[str, str]:
    """Save *results* as a completed run of a 5 kWh battery home named *run_name*, as a finished home job saves its run.

    The battery gives the run's results page its battery stat cards. Returns (run_id, run_name).
    """
    home = replace(make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0)), name=run_name)
    storage.save_home_run(run_id, home, results, calculate_summary(results))
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
    _e2e_storage.save_fleet_run(
        run_id,
        fleet,
        calculate_fleet_summary(fleet),
        [calculate_summary(home_results) for home_results in fleet.per_home_results],
        name=run_name,
    )
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
    preset_id = insert_saved_home_preset(_e2e_app.config["DATABASE"], "Small Urban", json.dumps(config))
    yield config
    with closing(sqlite3.connect(_e2e_app.config["DATABASE"])) as conn:
        with conn:
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

"""Shared fixtures for Playwright e2e tests.

Provides a live Flask server running in a background thread and
configures Playwright's base_url so tests can use relative paths.

Includes data-seeding fixtures for tests that need pre-existing
simulation runs (results pages, history interactions, compare page).
Also stubs the Run History page's runs-list API for tests that need it
empty or unanswered.

It imports nothing from playwright: tests/unit/test_e2e_job_wait.py runs
a copy of this module in the verify environment, which lacks the e2e extra.
"""

import json
import socket
import threading
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
import pytest
pytest.importorskip("werkzeug")
from flask import Flask
from werkzeug.serving import make_server

from solar_challenge.fleet import calculate_fleet_summary
from solar_challenge.home import calculate_summary
from solar_challenge.web.database import get_db
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.shared import get_job_manager
from solar_challenge.web.storage import RunStorage

from tests._finance_builders import make_fleet_results
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
def _e2e_db_path(_e2e_app: Flask) -> Path:
    """Path to the database the live server's app reads.

    create_app built its schema, so a fixture can seed it before the server starts.
    """
    return Path(_e2e_app.config["DATABASE"])


@pytest.fixture(scope="session")
def _e2e_data_dir(_e2e_app: Flask) -> Path:
    """Root data directory for the live server's run storage."""
    return Path(_e2e_app.config["DATA_DIR"])


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
# Data seeding helpers
# ---------------------------------------------------------------------------


def _make_summary_dict(
    *,
    total_generation_kwh: float = 100.0,
    total_demand_kwh: float = 80.0,
    total_self_consumption_kwh: float = 60.0,
    total_grid_import_kwh: float = 20.0,
    total_grid_export_kwh: float = 40.0,
    total_battery_charge_kwh: float = 10.0,
    total_battery_discharge_kwh: float = 8.0,
    peak_generation_kw: float = 4.0,
    peak_demand_kw: float = 3.5,
    self_consumption_ratio: float = 0.6,
    grid_dependency_ratio: float = 0.25,
    export_ratio: float = 0.4,
    simulation_days: int = 1,
    total_import_cost_gbp: float = 5.0,
    total_export_revenue_gbp: float = 3.0,
    net_cost_gbp: float = 2.0,
    strategy_name: str = "self_consumption",
) -> dict:
    return {
        "total_generation_kwh": total_generation_kwh,
        "total_demand_kwh": total_demand_kwh,
        "total_self_consumption_kwh": total_self_consumption_kwh,
        "total_grid_import_kwh": total_grid_import_kwh,
        "total_grid_export_kwh": total_grid_export_kwh,
        "total_battery_charge_kwh": total_battery_charge_kwh,
        "total_battery_discharge_kwh": total_battery_discharge_kwh,
        "peak_generation_kw": peak_generation_kw,
        "peak_demand_kw": peak_demand_kw,
        "self_consumption_ratio": self_consumption_ratio,
        "grid_dependency_ratio": grid_dependency_ratio,
        "export_ratio": export_ratio,
        "simulation_days": simulation_days,
        "total_import_cost_gbp": total_import_cost_gbp,
        "total_export_revenue_gbp": total_export_revenue_gbp,
        "net_cost_gbp": net_cost_gbp,
        "strategy_name": strategy_name,
    }


def _make_config_dict(
    *,
    pv_kw: float = 4.0,
    battery_kwh: float = 5.0,
    consumption_kwh: float = 3200.0,
) -> dict:
    return {
        "pv_config": {
            "capacity_kw": pv_kw,
            "azimuth": 180,
            "tilt": 35,
            "name": "",
            "module_efficiency": 0.20,
            "temperature_coefficient": -0.004,
            "inverter_efficiency": 0.96,
            "inverter_capacity_kw": None,
        },
        "load_config": {
            "annual_consumption_kwh": consumption_kwh,
            "household_occupants": 3,
            "name": "",
            "use_stochastic": False,
            "seed": None,
        },
        "battery_config": {
            "capacity_kwh": battery_kwh,
            "max_charge_kw": 2.5,
            "max_discharge_kw": 2.5,
            "name": "",
            "dispatch_strategy": None,
        },
        "heat_pump_config": None,
        "ev_config": None,
        "location": {
            "latitude": 51.45,
            "longitude": -2.58,
            "altitude": 11.0,
            "name": "Bristol, UK",
            "timezone": "Europe/London",
        },
        "name": "Seeded Test Run",
        "tariff_config": None,
        "dispatch_strategy": "greedy",
    }


def _make_parquet(run_dir: Path, n_minutes: int = 1440) -> None:
    """Write a minimal valid parquet file with the required columns."""
    index = pd.date_range(
        "2024-06-01", periods=n_minutes, freq="min", tz="Europe/London"
    )
    rng = np.random.default_rng(42)

    df = pd.DataFrame(
        {
            "generation_kw": rng.uniform(0, 4, n_minutes),
            "demand_kw": rng.uniform(0.2, 2, n_minutes),
            "self_consumption_kw": rng.uniform(0, 1.5, n_minutes),
            "battery_charge_kw": rng.uniform(0, 1, n_minutes),
            "battery_discharge_kw": rng.uniform(0, 0.8, n_minutes),
            "battery_soc_kwh": rng.uniform(0, 5, n_minutes),
            "grid_import_kw": rng.uniform(0, 1.5, n_minutes),
            "grid_export_kw": rng.uniform(0, 3, n_minutes),
            "import_cost_gbp": rng.uniform(0, 0.1, n_minutes),
            "export_revenue_gbp": rng.uniform(0, 0.05, n_minutes),
            "tariff_rate_per_kwh": np.full(n_minutes, 0.245),
        },
        index=index,
    )
    df.to_parquet(run_dir / "data.parquet", engine="pyarrow")


def _seed_run(
    db_path: Path,
    data_dir: Path,
    *,
    run_id: str | None = None,
    run_name: str = "Seeded Run",
    summary_overrides: dict | None = None,
) -> tuple[str, str]:
    """Insert a completed home run into the DB and write files to disk.

    Returns (run_id, run_name).
    """
    if run_id is None:
        run_id = uuid.uuid4().hex[:12]

    summary_dict = _make_summary_dict(**(summary_overrides or {}))
    config_dict = _make_config_dict()
    config_dict["name"] = run_name

    # Write files
    run_dir = data_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps(config_dict, indent=2))
    (run_dir / "summary.json").write_text(json.dumps(summary_dict, indent=2))
    _make_parquet(run_dir)

    # Insert DB row
    now = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                id, name, type, config_json, summary_json,
                status, error_message, created_at, completed_at,
                duration_seconds, n_homes, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                run_name,
                "home",
                json.dumps(config_dict),
                json.dumps(summary_dict),
                "completed",
                None,
                now,
                now,
                12.5,
                1,
                None,
            ),
        )

    return run_id, run_name


# ---------------------------------------------------------------------------
# Seeded data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def seeded_home_run(_e2e_db_path, _e2e_data_dir):
    """Insert a single completed home run. Returns (run_id, run_name)."""
    return _seed_run(
        _e2e_db_path,
        _e2e_data_dir,
        run_id="seed-home-001",
        run_name="Seeded Home Alpha",
    )


@pytest.fixture(scope="session")
def seeded_home_runs_pair(_e2e_db_path, _e2e_data_dir):
    """Insert 2 completed home runs with different summary values.

    Returns [(id1, name1), (id2, name2)].
    """
    r1 = _seed_run(
        _e2e_db_path,
        _e2e_data_dir,
        run_id="seed-cmp-001",
        run_name="Compare Run A",
        summary_overrides={
            "total_generation_kwh": 120.0,
            "total_demand_kwh": 90.0,
            "total_self_consumption_kwh": 70.0,
            "total_grid_import_kwh": 20.0,
            "total_grid_export_kwh": 50.0,
            "self_consumption_ratio": 0.583,
        },
    )
    r2 = _seed_run(
        _e2e_db_path,
        _e2e_data_dir,
        run_id="seed-cmp-002",
        run_name="Compare Run B",
        summary_overrides={
            "total_generation_kwh": 80.0,
            "total_demand_kwh": 100.0,
            "total_self_consumption_kwh": 50.0,
            "total_grid_import_kwh": 50.0,
            "total_grid_export_kwh": 30.0,
            "self_consumption_ratio": 0.625,
        },
    )
    return [r1, r2]


@pytest.fixture(scope="session")
def seeded_fleet_run(_e2e_db_path: Path, _e2e_data_dir: Path) -> tuple[str, str]:
    """Save a completed 2-home, 1-day fleet run through RunStorage. Returns (run_id, run_name).

    Its homes' results are make_fleet_results' constant-power series, so no simulation runs and no service is reached.
    """
    run_id, run_name = "seed-fleet-001", "Seeded Fleet Alpha"
    fleet = make_fleet_results(n_homes=2, self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)
    RunStorage(db_path=_e2e_db_path, data_dir=_e2e_data_dir).save_fleet_run(
        run_id,
        fleet,
        calculate_fleet_summary(fleet),
        [calculate_summary(home_results) for home_results in fleet.per_home_results],
        name=run_name,
    )
    return run_id, run_name


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

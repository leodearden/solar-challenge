"""Pytest configuration and shared fixtures."""

import os
import sys
import tempfile
import weakref
from collections.abc import Generator, Iterator
from typing import Any

import pytest
from pathlib import Path

from solar_challenge.weather import WeatherCache, set_weather_cache
from tests._network_guard import refusing_network
from tests._uv_env import isolated_uv_env

pytest_plugins = ["pytester"]

# Out of every default collection, even with `-o addopts=`; the offline lane runs it by explicit path.
collect_ignore = ["interpreter_matrix"]


@pytest.fixture
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def test_data_dir(project_root: Path) -> Path:
    """Return the test data directory."""
    return project_root / "tests" / "data"


@pytest.fixture
def callers_uv_lock_mode_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set UV_FROZEN=1 in this process's environment for the test, as the shell running the suite may.

    The orchestrator gives the offline lane no uv lock mode, so a test that runs a
    lane job's command as the lane runs it must pass whatever lock mode its own
    shell has: inherited, UV_FROZEN makes that command's `uv run --locked` an error.
    """
    monkeypatch.setenv("UV_FROZEN", "1")


@pytest.fixture
def uv_probe_environment(tmp_path: Path) -> dict[str, str]:
    """Return an isolated_uv_env whose uv project environment is the probe's own, fresh under *tmp_path*.

    No probe may touch an environment another run uses: inside the interpreter
    matrix, UV_PROJECT_ENVIRONMENT names that case's own venv. The offline lane,
    too, runs each job in a fresh one, as it cleans its worktree before every
    run; and like the verify, it takes its environment from the orchestrator,
    not from the shell running these tests.
    """
    return isolated_uv_env(tmp_path / "venv")


@pytest.fixture
def pytester_importing_test_helpers(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, project_root: Path
) -> pytest.Pytester:
    """pytester, whose sessions can import the tests/ helpers, such as tests._web_app, from whatever directory they run in."""
    monkeypatch.setenv("PYTHONPATH", str(project_root), prepend=os.pathsep)
    return pytester


@pytest.fixture
def pytester_under_root_conftest(pytester_importing_test_helpers: pytest.Pytester) -> pytest.Pytester:
    """pytester_importing_test_helpers, whose sessions run under a copy of this conftest."""
    pytester_importing_test_helpers.makeconftest(Path(__file__).read_text(encoding="utf-8"))
    return pytester_importing_test_helpers


@pytest.fixture(scope="session")
def _weather_cache_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("weather-caches")


@pytest.fixture
def weather_cache(_weather_cache_root: Path) -> Iterator[WeatherCache]:
    """An empty weather cache of the test's own, installed as the one get_tmy_data reads; seed a TMY with its put().

    It supersedes any cache installed before it, a broader-scoped fixture's
    included, and at teardown leaves none installed, so get_tmy_data falls back
    to the working directory's. A cache installed for a whole module or session
    therefore stops at the first test that uses this fixture.
    """
    cache = WeatherCache(cache_dir=Path(tempfile.mkdtemp(dir=_weather_cache_root)))
    set_weather_cache(cache)
    yield cache
    set_weather_cache(None)


_MARKS_OF_TESTS_ALLOWED_ONLINE = ("slow", "e2e")


@pytest.fixture(autouse=True)
def _run_offline_unless_slow_or_e2e(request: pytest.FixtureRequest) -> Iterator[None]:
    """Run each test not marked slow or e2e offline, and fail it at teardown if it reached the network.

    Such a test neither reads nor writes the working directory's .cache/weather,
    since get_tmy_data reads the test's own empty weather_cache, and every name
    lookup or connection it makes off this machine, from any thread, is refused.

    The guard spans the test and its function-scoped fixtures only. A class-,
    module- or session-scoped fixture is set up before the guard opens and torn
    down after it closes, so such a fixture runs unguarded and must keep itself offline.
    """
    if any(request.node.get_closest_marker(mark) for mark in _MARKS_OF_TESTS_ALLOWED_ONLINE):
        yield
        return
    request.getfixturevalue("weather_cache")
    with refusing_network() as refused:
        yield
    if refused:
        pytest.fail(
            f"{request.node.nodeid} reached the network ({', '.join(dict.fromkeys(refused))}); "
            "a test not marked slow or e2e runs offline: pass weather_data, seed the weather_cache fixture, "
            "or mark it slow if it needs a live service",
            pytrace=False,
        )


def _live_job_managers() -> frozenset[Any]:
    jobs_mod: Any = sys.modules.get("solar_challenge.web.jobs")
    if jobs_mod is None:
        return frozenset()
    return jobs_mod.live_managers()


@pytest.fixture(autouse=True)
def _shutdown_job_managers(_run_offline_unless_slow_or_e2e: None) -> Generator[None, None, None]:
    """At teardown, shut down the JobManagers created during the test, waiting for their in-flight simulations.

    Abandoned workers would otherwise hold up interpreter exit. It requests the
    offline guard, so the jobs it waits for still run offline and finish before
    the guard checks what the test reached.

    Autouse fixtures are set up after every broader-scoped fixture and before
    the other fixtures of their own scope. So a manager owned by a
    broader-scoped fixture (e.g. tests/e2e/conftest.py::_e2e_job_manager)
    already exists at setup and stays running for later tests; the fixture
    that owns it must shut it down in its own teardown.

    The web jobs module is looked up in sys.modules, never imported, so runs
    that never touch the web stack never load it.
    """
    preexisting = weakref.WeakSet(_live_job_managers())
    yield
    for manager in _live_job_managers():
        if manager not in preexisting:
            manager.shutdown(wait=True)

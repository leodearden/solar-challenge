"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import os
import sys
import tempfile
import weakref
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
from pathlib import Path

from tests._heap_freeze import freeze_the_heap_once
from tests._network_guard import refusing_network
from tests._uv_env import SharedUvEnvironments, isolated_uv_env

if TYPE_CHECKING:
    from solar_challenge.weather import WeatherCache

pytest_plugins = ["pytester"]

# Out of every default collection, even with `-o addopts=`; the offline lane runs them by explicit path.
collect_ignore = ["e2e", "interpreter_matrix", "css_build", "newest_releases"]


def pytest_collection_finish(session: pytest.Session) -> None:
    """Freeze the heap collection built, once per process, so the full collections during the run scan only what the tests create."""
    freeze_the_heap_once()


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
    """Return an isolated_uv_env whose uv project environment is the probe's own, fresh under *tmp_path* and never shared.

    It is for a probe whose commands must never sync into an environment another
    probe reads, as test_stale_uv_lock.py's stale project must not. Every other
    probe takes its environment from shared_uv_probe_environments.
    """
    return isolated_uv_env(tmp_path / "venv")


@pytest.fixture(scope="session")
def shared_uv_probe_environments(tmp_path_factory: pytest.TempPathFactory) -> SharedUvEnvironments:
    """Return the session's uv probe environments: the probes whose `uv run` options are the same share one, fresh and built once per session.

    No probe may touch an environment another run uses: inside the interpreter
    matrix, UV_PROJECT_ENVIRONMENT names that case's own venv. The offline lane
    and the per-task verify, too, run each command in a fresh one, as each
    starts from a clean worktree; and they take their environment from the
    orchestrator, not from the shell running these tests. Shared only by
    commands that give `uv run` the same options, an environment holds exactly
    what a fresh one would for each.
    """
    return SharedUvEnvironments(tmp_path_factory.mktemp("uv-probe-environments"))


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


@dataclass(frozen=True)
class _OfflineWindow:
    """What a test not marked slow runs in: its own empty weather cache, which CACHE_DIR_VARIABLE names while the window is open, and the destinations it was refused."""

    weather_cache: WeatherCache
    refused: list[str]


_OFFLINE_WINDOW_KEY = pytest.StashKey[_OfflineWindow]()


@contextmanager
def _open_offline_window() -> Iterator[_OfflineWindow]:
    """Open a test's window, which closes after the test is reported, where an error would abort the session.

    CACHE_DIR_VARIABLE names the window's weather cache until it closes, so default_weather() reads that cache.
    The first window imports solar_challenge.weather, before it refuses the network, so sessions that run no test never load it.
    """
    from solar_challenge.weather import CACHE_DIR_VARIABLE, WeatherCache

    with (
        tempfile.TemporaryDirectory(prefix="weather-cache-", ignore_cleanup_errors=True) as cache_dir,
        refusing_network() as refused,
        pytest.MonkeyPatch.context() as patch,
    ):
        patch.setenv(CACHE_DIR_VARIABLE, cache_dir)
        yield _OfflineWindow(WeatherCache(cache_dir=Path(cache_dir)), refused)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    """Run each test not marked slow offline, from the setup of its first fixture to the teardown of its last.

    Every fixture the test sets up or tears down, whatever its scope, runs in its
    window. There CACHE_DIR_VARIABLE names the test's own empty weather cache, so
    default_weather() reads it, in the test and in a child process that inherits its
    environment. Every name lookup or connection off this machine, from any thread,
    is refused, as is every HTTP(S) request the test's child processes send through
    the standard proxy variables.
    """
    if item.get_closest_marker("slow"):
        return (yield)
    with _open_offline_window() as window:
        item.stash[_OFFLINE_WINDOW_KEY] = window
        try:
            return (yield)
        finally:
            del item.stash[_OFFLINE_WINDOW_KEY]


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item) -> Generator[None, object, object]:
    """Fail a test run offline at teardown if it, or a fixture it set up or tore down, reached the network.

    A teardown that raised has already failed the test, and its error is reported alone.
    """
    torn_down = yield
    window = item.stash.get(_OFFLINE_WINDOW_KEY, None)
    if window is not None and window.refused:
        pytest.fail(
            f"{item.nodeid} reached the network ({', '.join(dict.fromkeys(window.refused))}); "
            "a test not marked slow runs offline, with every fixture it sets up or tears down: "
            "pass simulate_home its weather, seed the weather_cache fixture, or mark it slow if it needs a live service",
            pytrace=False,
        )
    return torn_down


@pytest.fixture
def weather_cache(request: pytest.FixtureRequest) -> WeatherCache:
    """The test's own empty weather cache, which default_weather() reads in the test and in a child process that inherits its environment; seed a TMY with its put()."""
    window: _OfflineWindow | None = request.node.stash.get(_OFFLINE_WINDOW_KEY, None)
    if window is None:
        pytest.fail(
            f"{request.node.nodeid} is marked slow, so default_weather() reads the weather cache its "
            "environment names, else the working directory's; weather_cache serves a test that runs offline",
            pytrace=False,
        )
    return window.weather_cache


def _live_job_managers() -> frozenset[Any]:
    jobs_mod: Any = sys.modules.get("solar_challenge.web.jobs")
    if jobs_mod is None:
        return frozenset()
    return jobs_mod.live_managers()


@pytest.fixture(autouse=True)
def _shutdown_job_managers() -> Generator[None, None, None]:
    """At teardown, shut down the JobManagers created during the test, waiting for their in-flight simulations.

    Abandoned workers would otherwise hold up interpreter exit. The test's
    teardown runs in its offline window, so the jobs it waits for still run
    offline and finish before the window checks what the test reached.

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

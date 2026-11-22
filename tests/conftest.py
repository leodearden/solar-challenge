"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import os
import sys
import tempfile
import weakref
from collections.abc import Callable, Generator, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
from pathlib import Path

from tests._collect_only import Collection, uv_is_installed
from tests._heap_freeze import freeze_the_heap_once
from tests._lane_collection import collect_lane_job_once
from tests._network_guard import refusing_network
from tests._once_per_run import run_shared_path
from tests._project_temp_root import name_the_project_temp_root, pre_fixture_temp_dir
from tests._repository_paths import REPOSITORY_ROOT
from tests._uv_env import SharedUvEnvironments, isolated_uv_env

if TYPE_CHECKING:
    from solar_challenge.weather import WeatherCache

pytest_plugins = ["pytester"]

# Out of every default collection, even with `-o addopts=`; the offline lane runs them by explicit path.
collect_ignore = ["e2e", "interpreter_matrix", "css_build", "newest_releases"]


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Name the project's temp root for *config*'s session before any other plugin configures (tests/_project_temp_root.py), and drop COLUMNS and LINES from os.environ and from the C environment beneath it, so no process of the suite, serial or an xdist worker, holds a terminal size, and no child a test starts inherits one.

    A console the CLI builds at import then reads COLUMNS when it prints.
    tests/unit/test_parallel_suite.py says where the two come from.
    """
    name_the_project_temp_root(config)
    for name in ("COLUMNS", "LINES"):
        os.environ.pop(name, None)
        os.unsetenv(name)


def pytest_collection_finish(session: pytest.Session) -> None:
    """Freeze the heap collection built, once per process, so the full collections during the run scan only what the tests create."""
    freeze_the_heap_once()


@pytest.fixture
def project_root() -> Path:
    """Return the repository root, tests/_repository_paths.py's REPOSITORY_ROOT."""
    return REPOSITORY_ROOT


@pytest.fixture
def test_data_dir(project_root: Path) -> Path:
    """Return the test data directory."""
    return project_root / "tests" / "data"


@pytest.fixture
def e2e_conftest(project_root: Path) -> Path:
    """Return the e2e suite's conftest, tests/e2e/conftest.py, which a pytester session copies to run its tests as that suite runs them."""
    return project_root / "tests" / "e2e" / "conftest.py"


_CALLERS_FROZEN_LOCK_MODE = ("UV_FROZEN", "1")


@pytest.fixture
def callers_uv_lock_mode_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set _CALLERS_FROZEN_LOCK_MODE in this process's environment for the test, as the shell running the suite may.

    The orchestrator gives the offline lane no uv lock mode, so a test that runs a
    lane job's command as the lane runs it must pass whatever lock mode its own
    shell has: inherited, a frozen one makes that command's `uv run --locked` an error.
    """
    monkeypatch.setenv(*_CALLERS_FROZEN_LOCK_MODE)


@pytest.fixture
def uv_probe_environment(tmp_path: Path) -> dict[str, str]:
    """Return an isolated_uv_env whose uv project environment is the probe's own, fresh under *tmp_path* and never shared.

    It is for a probe whose commands must never sync into an environment another
    probe reads, as tests/unit/test_stale_uv_lock.py's stale project must not. Every other
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


def _assert_asked_with_uv_installed_and_its_lock_mode_frozen(job: str) -> None:
    """Assert that the test asking lane_job_collection for *job* runs as @requires_uv and callers_uv_lock_mode_is_frozen make it run: uv on PATH, and _CALLERS_FROZEN_LOCK_MODE set."""
    assert uv_is_installed(), (
        f"a test asked lane_job_collection for the {job!r} lane job where uv is not on PATH. Any test that asks may be "
        "the one that collects the job, which runs it through uv, so each carries @requires_uv, which skips it where "
        "uv is not installed"
    )
    variable, frozen = _CALLERS_FROZEN_LOCK_MODE
    lock_mode = os.environ.get(variable)
    assert lock_mode == frozen, (
        f"a test asked lane_job_collection for the {job!r} lane job with {variable}={lock_mode!r}. Any test that asks may "
        "be the one that collects the job for its run, so each carries "
        '@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen"); else the job is collected without the uv lock '
        "mode a caller's shell may freeze, and every later test that asks reads that collection"
    )


@pytest.fixture(scope="session")
def lane_job_collection(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    shared_uv_probe_environments: SharedUvEnvironments,
) -> Callable[[Path, str], Collection]:
    """Return each offline-lane job's collection as the lane runs it, read as lane_job_collection(project_root, name).

    The first test of the run, on whichever worker, that asks for a job collects
    it through collect_lane_job_once, in the environment its worker's
    shared_uv_probe_environments builds at that call, inside that test's
    offline window. Every later test, on any worker, reads that collection. Any
    test that asks may be the one that collects, so each carries @requires_uv
    and @pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen"), and every
    call, not only the one that collects, first asserts both hold.
    """
    collections = run_shared_path(request, tmp_path_factory, "lane-job-collections")

    def collected(project_root: Path, name: str) -> Collection:
        _assert_asked_with_uv_installed_and_its_lock_mode_frozen(name)
        return collect_lane_job_once(collections, project_root, name, env_for=shared_uv_probe_environments.for_command)

    return collected


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


@pytest.fixture
def pytester_sessions_read_the_project_ini(pytester: pytest.Pytester, project_root: Path) -> None:
    """Copy this project's pyproject.toml into pytester's directory, so the sessions pytester starts read the project's pytest ini: its addopts, markers, strict_markers and filterwarnings."""
    pytester.makepyprojecttoml((project_root / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture
def pytester_laid_out_as_the_e2e_suite(
    pytester_under_root_conftest: pytest.Pytester,
    pytester_sessions_read_the_project_ini: None,
    e2e_conftest: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> pytest.Pytester:
    """pytester_under_root_conftest, laid out as the offline lane's e2e job runs tests/e2e: its sessions read the project ini, and e2e/ holds a copy of the e2e conftest.

    A session collects e2e/ only if it names it, as the lane's job names tests/e2e, since this conftest's collect_ignore keeps e2e/ out of every other collection.
    Like the lane's, its sessions start with no weather cache directory named, not with the variable of the window that runs the test.
    """
    from solar_challenge.weather import CACHE_DIR_VARIABLE

    monkeypatch.delenv(CACHE_DIR_VARIABLE, raising=False)
    pytester_under_root_conftest.makepyfile(**{"e2e/conftest": e2e_conftest.read_text(encoding="utf-8")})
    return pytester_under_root_conftest


@pytest.fixture
def sessions_temp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return the temp dir under the test's tmp_path that TMPDIR names for the sessions the test runs, so they write nowhere outside tmp_path."""
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    monkeypatch.setenv("TMPDIR", str(temp_dir))
    return temp_dir


@dataclass(frozen=True)
class _OfflineWindow:
    """What a test not marked slow runs in: its own empty weather cache, which CACHE_DIR_VARIABLE names while the window is open, and the destinations it was refused."""

    weather_cache: WeatherCache
    refused: list[str]


_OFFLINE_WINDOW_KEY = pytest.StashKey[_OfflineWindow]()


@contextmanager
def _open_offline_window(temp_dir: Path) -> Iterator[_OfflineWindow]:
    """Open a test's window, which closes after the test is reported, where an error would abort the session.

    CACHE_DIR_VARIABLE names the window's weather cache, a temp dir in *temp_dir*, until it closes, so default_weather() reads that cache.
    The first window imports solar_challenge.weather, before it refuses the network, so sessions that run no test never load it.
    """
    from solar_challenge.weather import CACHE_DIR_VARIABLE, WeatherCache

    with (
        tempfile.TemporaryDirectory(prefix="weather-cache-", dir=temp_dir, ignore_cleanup_errors=True) as cache_dir,
        refusing_network() as refused,
        pytest.MonkeyPatch.context() as patch,
    ):
        patch.setenv(CACHE_DIR_VARIABLE, cache_dir)
        yield _OfflineWindow(WeatherCache(cache_dir=Path(cache_dir)), refused)


@contextmanager
def _pytest_sessions_it_starts_run_serially() -> Iterator[None]:
    """Resolve `-n auto` to no workers in every pytest session started while it is open, through pytest-xdist's PYTEST_XDIST_AUTO_NUM_WORKERS.

    The suite already runs on a worker per core; tests/unit/test_parallel_suite.py
    says what a session that started its own would do to it.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "0")
        yield


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    """Run each test not marked slow offline, from the setup of its first fixture to the teardown of its last.

    Every fixture the test sets up or tears down, whatever its scope, runs in its
    window. There CACHE_DIR_VARIABLE names the test's own empty weather cache, so
    default_weather() reads it, in the test and in a child process that inherits its
    environment. Every name lookup or connection off this machine, from any thread,
    is refused, as is every HTTP(S) request the test's child processes send through
    the standard proxy variables. Over the same span, a pytest session the test
    starts runs `-n auto` in its own process, while a slow test's sessions, such as
    the lanes' verify runs, keep a worker per core.
    """
    if item.get_closest_marker("slow"):
        return (yield)
    with _open_offline_window(pre_fixture_temp_dir(item.config)) as window, _pytest_sessions_it_starts_run_serially():
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


@pytest.fixture(autouse=True)
def closes_at_teardown() -> Iterator[ExitStack]:
    """The test's closing stack: each close a builder fixture registers on it runs at the test's teardown, the last registered first.

    Autouse fixtures are set up before, and torn down after, the other fixtures of their own
    scope, so every gate the test's fixtures hold, such as blocking_simulation, is released
    before a close waits for the jobs it held.
    """
    with ExitStack() as closes:
        yield closes


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

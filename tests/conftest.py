"""Pytest configuration and shared fixtures."""

import sys
import weakref
from collections.abc import Generator
from typing import Any

import pytest
from pathlib import Path

from tests._uv_env import isolated_uv_env

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


def _live_job_managers() -> frozenset[Any]:
    jobs_mod: Any = sys.modules.get("solar_challenge.web.jobs")
    if jobs_mod is None:
        return frozenset()
    return jobs_mod.live_managers()


@pytest.fixture(autouse=True)
def _shutdown_job_managers() -> Generator[None, None, None]:
    """At teardown, shut down the JobManagers created during the test, waiting for their in-flight simulations.

    Abandoned workers would otherwise hold up interpreter exit.

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

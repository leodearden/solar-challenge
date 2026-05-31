"""Pytest configuration and shared fixtures."""

import sys
from collections.abc import Generator
from typing import Any

import pytest
from pathlib import Path


@pytest.fixture
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def test_data_dir(project_root: Path) -> Path:
    """Return the test data directory."""
    return project_root / "tests" / "data"


@pytest.fixture(autouse=True)
def _shutdown_job_managers() -> Generator[None, None, None]:
    """Drain every JobManager executor after each test.

    Guard on sys.modules so pure non-web test runs never import the
    optional web stack (avoids pulling in Flask/web deps unnecessarily
    and silently failing when the ``web`` extra is not installed).

    For web tests this fixture runs shutdown_all_managers(wait=True) on
    teardown, draining any in-flight simulations started by submit-only
    endpoint tests.  This eliminates the ~48 s process-exit linger that
    occurred when abandoned workers were joined by the interpreter's own
    _python_exit handler at the end of the suite.
    """
    yield
    jobs_mod: Any = sys.modules.get("solar_challenge.web.jobs")
    if jobs_mod is not None:
        jobs_mod.shutdown_all_managers(wait=True)

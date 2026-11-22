# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard's Flask test app, the factory of the job manager its jobs run on, a client of it, the RunStorage it keeps its runs in, and its template macros, for the unit tests that drive the app; and new_job_manager, which builds a JobManager the test's teardown shuts down.

The app's jobs run on the JobManager the jobs fixture builds, tests/_web_app.py's
jobs_in_this_process. A test module, class or package conftest whose tests need another
job manager, such as a double, overrides jobs; one whose tests need a RunStorage of no app
defines its own storage. pytest uses those instead of these.

Nothing here imports the web extra when it loads:
tests/unit/test_conftests_need_no_web_extra.py says why.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests._server_drawn_badges import dashboard_macros_of
from tests._web_app import jobs_in_this_process, run_storage_of

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient

    from solar_challenge.fleet import HomeSimulator
    from solar_challenge.web.dashboard import JobManagerFactory
    from solar_challenge.web.jobs import JobManager
    from solar_challenge.web.storage import RunStorage
    from tests._web_app import BuildApp
    from tests._web_job_runner import NewJobManager


@pytest.fixture
def jobs() -> JobManagerFactory:
    """The factory of the JobManager the app fixture's app runs its jobs on: jobs_in_this_process, unless a test module or class overrides it."""
    return jobs_in_this_process


@pytest.fixture
def app(build_app: BuildApp, tmp_path: Path, jobs: JobManagerFactory) -> Flask:
    """The dashboard app in testing mode, its database and run files under the test's tmp_path, its jobs run on the manager jobs builds; the test's teardown closes it."""
    return build_app(tmp_path, jobs=jobs)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A test client of the app fixture's app."""
    return app.test_client()


@pytest.fixture
def storage(app: Flask) -> RunStorage:
    """The RunStorage the app fixture's app keeps its runs in, which its pages read."""
    return run_storage_of(app)


@pytest.fixture
def new_job_manager(closes_at_teardown: ExitStack) -> NewJobManager:
    """Build a JobManager over a RunStorage whose jobs run through tests/_web_job_runner.py's runner_of(home_simulator), shut down at the test's teardown once its running jobs finish.

    Called as new_job_manager(storage, home_simulator, **options), each option going to JobManager.
    """
    from solar_challenge.web.jobs import JobManager
    from tests._web_job_runner import runner_of

    def new(storage: RunStorage, home_simulator: HomeSimulator, /, **options: Any) -> JobManager:
        manager = JobManager(storage, runner=runner_of(home_simulator), **options)
        closes_at_teardown.callback(manager.shutdown, wait=True)
        return manager

    return new


@pytest.fixture
def macros(app: Flask) -> Any:
    """The public macros of components/macros.html, as callables that return their markup."""
    return dashboard_macros_of(app)

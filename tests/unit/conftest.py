# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard's Flask test app, a client of it, the RunStorage it keeps its runs in, and its template macros, for the unit tests that drive the app; and new_job_manager, which builds a JobManager the test's teardown shuts down.

The client's requests reach the JobManager that create_app built. A test module or
package conftest whose tests need another job manager defines its own client, and one
whose tests need a RunStorage of no app defines its own storage; pytest uses those
instead of these.

Nothing here imports the web extra when it loads:
tests/unit/test_conftests_need_no_web_extra.py says why.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests._server_drawn_badges import dashboard_macros_of
from tests._web_app import build_test_app, release_store_lock, run_storage_of

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient

    from solar_challenge.fleet import HomeSimulator
    from solar_challenge.web.jobs import JobManager
    from solar_challenge.web.storage import RunStorage
    from tests._web_job_runner import NewJobManager


@pytest.fixture
def app(tmp_path: Path) -> Iterator[Flask]:
    """The dashboard app in testing mode, its database and run files under the test's tmp_path; its teardown releases the app's store lock."""
    app = build_test_app(tmp_path)
    yield app
    release_store_lock(app)


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

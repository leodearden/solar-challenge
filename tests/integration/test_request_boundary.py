# SPDX-License-Identifier: AGPL-3.0-or-later
"""The request boundary's integration gate: docs/prds/web-request-boundary.md §6 rows L5, R1, R2 and R3, and the presence rule, across the CLI and every /api POST route.

Row L5 holds the CLI and the web to one location grammar and one message. Rows R1, R2 and
R3 run over every POST route of the api blueprint's url_map, so a route added later fails
until it is tabled. Every expected refusal text is the reader's own, computed by calling the
reader, never a literal copy.
"""

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import NonCallableMagicMock

import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient
from typer.testing import CliRunner

from solar_challenge.cli.main import app as cli_app
from tests._cli_stderr_text import stderr_text
from tests._job_manager_double import autospecced_job_manager
from tests._web_app import app_builder


@pytest.fixture
def job_manager() -> NonCallableMagicMock:
    """The dashboard's JobManager, autospecced, whose submissions answer a job and run id each."""
    job_manager = autospecced_job_manager()
    job_manager.submit_home_job.return_value = ("job-home", "run-home")
    job_manager.submit_fleet_job.return_value = ("job-fleet", "run-fleet")
    return job_manager


@pytest.fixture
def client(tmp_path: Path, closes_at_teardown: ExitStack, job_manager: NonCallableMagicMock) -> FlaskClient:
    """A client of the real dashboard app over *job_manager*, which answers a defect as a production app does rather than raising it into the client."""
    app = app_builder(closes_at_teardown)(tmp_path / "dashboard", jobs=lambda storage: job_manager)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    return app.test_client()


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("londn", id="misspelt-preset"),
        pytest.param("51.5;-0.1", id="semicolon"),
        pytest.param("51.5,-0.1,x", id="altitude-not-a-number"),
        pytest.param("95,0", id="latitude-out-of-range"),
    ],
)
def test_the_cli_and_the_web_refuse_a_location_string_with_one_message(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str
) -> None:
    """Row L5: `home run --location` and POST /api/simulate/home read a location string with one grammar, and refuse it with one message."""
    monkeypatch.chdir(tmp_path)

    web = client.post("/api/simulate/home", json={"location": text})
    result = CliRunner().invoke(cli_app, ["home", "run", "--location", text], catch_exceptions=False)

    assert web.status_code == 400
    assert (result.exit_code, stderr_text(result)) == (1, f"Configuration error: {web.get_json()['error']}")

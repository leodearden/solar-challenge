# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_web_app.py, which builds the web tests' Flask app over the job manager a factory builds, names the database file it gives that app, and finds the Database it keeps its tables in and the RunStorage it keeps its runs in; for tests/conftest.py's build_app fixture, which builds an app the test's teardown closes; and for the app, client and storage fixtures tests/unit/conftest.py builds with it."""

from contextlib import ExitStack
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("flask")

from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.dashboard import dashboard_of
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.storage import RunStorage
from solar_challenge.web.store_lock import StoreLocked, acquire_store_lock
from tests._blocked_imports import extra_modules, import_with_modules_blocked
from tests._finance_builders import make_home_config, make_sim_results
from tests._web_app import BuildApp, database_of, database_path_in, jobs_in_this_process, point_store_config_at_a_missing_directory, run_storage_of
from tests._web_runs import store_home_run


def test_importing_the_helper_needs_no_web_extra(project_root: Path) -> None:
    """tests/unit/conftest.py imports the helper when it loads, and a run without the web extra must skip the tests that need it, not abort."""
    result = import_with_modules_blocked("tests._web_app", extra_modules(project_root, "web"), project_root)

    assert result.returncode == 0, result.stderr


def test_the_app_runs_in_testing_mode_with_its_data_under_the_given_directory(
    build_app: BuildApp, tmp_path: Path
) -> None:
    app = build_app(tmp_path)

    assert app.testing
    assert Path(app.config["DATABASE"]).is_relative_to(tmp_path)
    assert Path(app.config["DATA_DIR"]) == tmp_path


def test_database_path_in_names_the_database_file_of_the_app_built_on_its_directory(
    build_app: BuildApp, tmp_path: Path
) -> None:
    app = build_app(tmp_path)

    assert database_of(app).path == database_path_in(tmp_path)


def test_the_app_serves_a_run_saved_to_its_run_storage_after_its_store_config_names_a_missing_directory(
    build_app: BuildApp, tmp_path: Path
) -> None:
    """A RunStorage rebuilt from the app's store config would save the run where the app does not read it."""
    app = build_app(tmp_path / "data")
    point_store_config_at_a_missing_directory(app, tmp_path / "missing")

    store_home_run(run_storage_of(app), "north-roof", make_home_config(), make_sim_results(days=1), name="North Roof")

    response = app.test_client().get("/api/history/runs/north-roof")
    assert response.status_code == 200
    assert response.get_json()["name"] == "North Roof"


def test_the_app_serves_a_row_written_to_its_database_after_its_store_config_names_a_missing_directory(
    build_app: BuildApp, tmp_path: Path
) -> None:
    """A Database rebuilt from the app's store config could not open its file, whose directory is missing."""
    app = build_app(tmp_path / "data")
    point_store_config_at_a_missing_directory(app, tmp_path / "missing")

    with database_of(app).transaction() as conn:
        conn.execute(
            "INSERT INTO runs (id, name, type, status, created_at) VALUES (?, ?, ?, ?, ?)",
            ("north-roof", "North Roof", "home", "running", "2025-06-02T09:00:00"),
        )

    response = app.test_client().get("/api/history/runs/north-roof")
    assert response.status_code == 200
    assert response.get_json()["name"] == "North Roof"


def test_after_an_app_is_closed_an_app_builds_on_the_same_directory_and_reads_the_store_the_first_left(
    build_app: BuildApp, tmp_path: Path
) -> None:
    first = build_app(tmp_path)
    store_home_run(run_storage_of(first), "north-roof", make_home_config(), make_sim_results(days=1), name="North Roof")

    dashboard_of(first).close()

    response = build_app(tmp_path).test_client().get("/api/history/runs/north-roof")
    assert response.status_code == 200
    assert response.get_json()["name"] == "North Roof"


def test_a_test_may_close_the_app_fixtures_app_itself(app: Flask, build_app: BuildApp, tmp_path: Path) -> None:
    """The test's teardown then closes it again, which must be harmless."""
    dashboard_of(app).close()

    build_app(tmp_path)


_A_DAY = (pd.Timestamp("2024-06-01", tz="UTC"), pd.Timestamp("2024-06-02", tz="UTC"))


def _store_lock_is_free(store: Path) -> bool:
    """Whether this process can take the lock on *store*, which it then releases at once."""
    try:
        acquire_store_lock(store).release()
    except StoreLocked:
        return False
    return True


def _closed(app: Flask, store: Path) -> bool:
    """Whether *app*, whose store is *store*, is closed: its jobs refuse a new one, and its store's lock is free."""
    try:
        dashboard_of(app).jobs.submit_home_job(make_home_config(), *_A_DAY)
    except RuntimeError:
        return _store_lock_is_free(store)
    pytest.fail("the app's jobs accepted a job, so it is not closed")


def test_the_app_the_jobs_factory_is_given_runs_its_jobs_on_the_manager_the_factory_builds(
    build_app: BuildApp, tmp_path: Path
) -> None:
    built: list[JobManager] = []

    def jobs(storage: RunStorage) -> JobManager:
        built.append(jobs_in_this_process(storage))
        return built[-1]

    app = build_app(tmp_path, jobs=jobs)

    assert [dashboard_of(app).jobs] == built


def test_an_app_build_app_built_is_closed_when_the_tests_closing_stack_closes(
    build_app: BuildApp, closes_at_teardown: ExitStack, tmp_path: Path
) -> None:
    """tests/conftest.py's closes_at_teardown closes its stack at the test's teardown, after every other fixture of the test is torn down."""
    app = build_app(tmp_path)
    assert not _store_lock_is_free(tmp_path)

    closes_at_teardown.close()

    assert _closed(app, tmp_path)


def test_the_app_fixtures_app_is_closed_when_the_tests_closing_stack_closes(
    app: Flask, closes_at_teardown: ExitStack, tmp_path: Path
) -> None:
    closes_at_teardown.close()

    assert _closed(app, tmp_path)


def test_the_app_fixture_keeps_its_data_under_the_tests_own_tmp_path(app: Flask, tmp_path: Path) -> None:
    assert Path(app.config["DATA_DIR"]) == tmp_path


def test_the_client_fixture_is_a_client_of_the_app_fixture(app: Flask, client: FlaskClient) -> None:
    assert client.application is app


def test_the_storage_fixture_is_the_run_storage_the_app_fixture_keeps_its_runs_in(
    app: Flask, storage: RunStorage
) -> None:
    assert storage is run_storage_of(app)


@pytest.fixture
def exported_secret_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """A SECRET_KEY exported in the environment, with HOME pointed at tmp_path so create_app's own key lookup cannot reach the real home directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    key = "a-key-from-the-environment"
    monkeypatch.setenv("SECRET_KEY", key)
    return key


def test_by_default_the_builder_supplies_the_apps_secret_key(
    build_app: BuildApp, exported_secret_key: str, tmp_path: Path
) -> None:
    """By default the app's key comes from the builder, not from create_app's own lookup, which reads, and can write, a key persisted under the home directory."""
    app = build_app(tmp_path)

    assert app.secret_key
    assert app.secret_key != exported_secret_key


@pytest.mark.usefixtures("exported_secret_key")
def test_a_given_secret_key_becomes_the_apps_key(build_app: BuildApp, tmp_path: Path) -> None:
    assert build_app(tmp_path, secret_key="a-given-key").secret_key == "a-given-key"


def test_secret_key_none_leaves_the_apps_key_to_create_apps_own_lookup(
    build_app: BuildApp, exported_secret_key: str, tmp_path: Path
) -> None:
    assert build_app(tmp_path, secret_key=None).secret_key == exported_secret_key


def test_the_store_config_is_pointed_into_the_missing_directory_which_stays_missing(
    build_app: BuildApp, tmp_path: Path
) -> None:
    app = build_app(tmp_path / "data")
    directory = tmp_path / "missing"

    point_store_config_at_a_missing_directory(app, directory)

    assert Path(app.config["DATABASE"]).parent == directory
    assert Path(app.config["DATA_DIR"]) == directory
    assert not directory.exists()


def test_an_existing_directory_is_refused_and_the_store_config_is_left_as_it_was(
    build_app: BuildApp, tmp_path: Path
) -> None:
    app = build_app(tmp_path / "data")
    store_config = (app.config["DATABASE"], app.config["DATA_DIR"])
    existing = tmp_path / "existing"
    existing.mkdir()

    with pytest.raises(AssertionError):
        point_store_config_at_a_missing_directory(app, existing)

    assert (app.config["DATABASE"], app.config["DATA_DIR"]) == store_config

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_web_app.py, which builds the web tests' Flask app, finds the Database it keeps its tables in and the RunStorage it keeps its runs in, and releases the store lock it holds, and for the app, client and storage fixtures tests/unit/conftest.py builds with it, the app fixture releasing its app's store lock at teardown."""

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("flask")

from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.storage import RunStorage
from solar_challenge.web.store_lock import acquire_store_lock
from tests._finance_builders import make_home_config, make_sim_results
from tests._web_app import build_test_app, database_of, point_store_config_at_a_missing_directory, release_store_lock, run_storage_of
from tests._web_runs import store_home_run


def test_importing_the_helper_needs_no_web_extra(project_root: Path) -> None:
    """tests/unit/conftest.py imports the helper when it loads, and a run without the web extra must skip the tests that need it, not abort."""
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.modules['flask'] = None; import tests._web_app"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr


def test_the_app_runs_in_testing_mode_with_its_data_under_the_given_directory(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)

    assert app.testing
    assert Path(app.config["DATABASE"]).is_relative_to(tmp_path)
    assert Path(app.config["DATA_DIR"]) == tmp_path


def test_the_app_serves_a_run_saved_to_its_run_storage_after_its_store_config_names_a_missing_directory(
    tmp_path: Path,
) -> None:
    """A RunStorage rebuilt from the app's store config would save the run where the app does not read it."""
    app = build_test_app(tmp_path / "data")
    point_store_config_at_a_missing_directory(app, tmp_path / "missing")

    store_home_run(run_storage_of(app), "north-roof", make_home_config(), make_sim_results(days=1), name="North Roof")

    response = app.test_client().get("/api/history/runs/north-roof")
    assert response.status_code == 200
    assert response.get_json()["name"] == "North Roof"


def test_the_app_serves_a_row_written_to_its_database_after_its_store_config_names_a_missing_directory(
    tmp_path: Path,
) -> None:
    """A Database rebuilt from the app's store config could not open its file, whose directory is missing."""
    app = build_test_app(tmp_path / "data")
    point_store_config_at_a_missing_directory(app, tmp_path / "missing")

    with database_of(app).transaction() as conn:
        conn.execute(
            "INSERT INTO runs (id, name, type, status, created_at) VALUES (?, ?, ?, ?, ?)",
            ("north-roof", "North Roof", "home", "running", "2025-06-02T09:00:00"),
        )

    response = app.test_client().get("/api/history/runs/north-roof")
    assert response.status_code == 200
    assert response.get_json()["name"] == "North Roof"


def test_after_its_store_lock_is_released_an_app_builds_on_the_same_directory_and_reads_the_store_the_first_left(
    tmp_path: Path,
) -> None:
    first = build_test_app(tmp_path)
    store_home_run(run_storage_of(first), "north-roof", make_home_config(), make_sim_results(days=1), name="North Roof")

    release_store_lock(first)

    response = build_test_app(tmp_path).test_client().get("/api/history/runs/north-roof")
    assert response.status_code == 200
    assert response.get_json()["name"] == "North Roof"


def test_a_test_may_release_the_app_fixtures_store_lock_itself(app: Flask, tmp_path: Path) -> None:
    """The app fixture's teardown then releases the lock again, which must be harmless."""
    release_store_lock(app)

    release_store_lock(build_test_app(tmp_path))


@pytest.fixture
def store_locked_after_the_app_fixture(tmp_path: Path) -> Iterator[None]:
    """After the test, take and release the lock on the store in tmp_path.

    A test that requests it before app tears it down after the app fixture, so a lock the
    app fixture kept raises StoreLocked here and errors the test at teardown.
    """
    yield
    acquire_store_lock(tmp_path).release()


def test_the_app_fixture_releases_its_store_lock_at_teardown(
    store_locked_after_the_app_fixture: None, app: Flask, tmp_path: Path
) -> None:
    """store_locked_after_the_app_fixture, before app here, locks the app's store after the app fixture's teardown."""
    assert Path(app.config["DATA_DIR"]) == tmp_path


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
    exported_secret_key: str, tmp_path: Path
) -> None:
    """By default the app's key comes from the builder, not from create_app's own lookup, which reads, and can write, a key persisted under the home directory."""
    app = build_test_app(tmp_path)

    assert app.secret_key
    assert app.secret_key != exported_secret_key


@pytest.mark.usefixtures("exported_secret_key")
def test_a_given_secret_key_becomes_the_apps_key(tmp_path: Path) -> None:
    assert build_test_app(tmp_path, secret_key="a-given-key").secret_key == "a-given-key"


def test_secret_key_none_leaves_the_apps_key_to_create_apps_own_lookup(
    exported_secret_key: str, tmp_path: Path
) -> None:
    assert build_test_app(tmp_path, secret_key=None).secret_key == exported_secret_key


def test_the_store_config_is_pointed_into_the_missing_directory_which_stays_missing(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path / "data")
    directory = tmp_path / "missing"

    point_store_config_at_a_missing_directory(app, directory)

    assert Path(app.config["DATABASE"]).parent == directory
    assert Path(app.config["DATA_DIR"]) == directory
    assert not directory.exists()


def test_an_existing_directory_is_refused_and_the_store_config_is_left_as_it_was(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path / "data")
    store_config = (app.config["DATABASE"], app.config["DATA_DIR"])
    existing = tmp_path / "existing"
    existing.mkdir()

    with pytest.raises(AssertionError):
        point_store_config_at_a_missing_directory(app, existing)

    assert (app.config["DATABASE"], app.config["DATA_DIR"]) == store_config

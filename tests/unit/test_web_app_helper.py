# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_web_app.py, the shared builder of the web tests' Flask app, and for the app and client fixtures tests/unit/conftest.py builds with it."""

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

from flask import Flask
from flask.testing import FlaskClient

from tests._web_app import build_test_app, point_store_config_at_a_missing_directory


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


def test_the_app_fixture_keeps_its_data_under_the_tests_own_tmp_path(app: Flask, tmp_path: Path) -> None:
    assert Path(app.config["DATA_DIR"]) == tmp_path


def test_the_client_fixture_is_a_client_of_the_app_fixture(app: Flask, client: FlaskClient) -> None:
    assert client.application is app


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

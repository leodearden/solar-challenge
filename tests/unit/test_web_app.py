# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the web dashboard's application factory."""

import importlib
import re
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

from tests._web_app import build_test_app


def _uncache_module(monkeypatch: pytest.MonkeyPatch, module: str) -> None:
    """Make the next import of *module* run it afresh; the cached module comes back after the test.

    A fresh import that succeeds also rebinds the module's attribute on its parent package,
    so that attribute is restored along with the sys.modules entry.
    """
    package, _, name = module.rpartition(".")
    monkeypatch.delitem(sys.modules, module, raising=False)
    monkeypatch.delattr(importlib.import_module(package), name, raising=False)


_DASHBOARD_FOLDERS = ("templates", "static")


def _import_app_from_a_web_package_lacking(
    missing: str, web_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make the next import of solar_challenge.web.app load a copy of app.py from *web_dir*, which holds every dashboard folder but *missing*, as from an install whose web package lacks that folder; the real module, imported here if need be, comes back after the test."""
    web_package = importlib.import_module("solar_challenge.web")
    importlib.import_module("solar_challenge.web.app")
    web_dir.mkdir()
    shutil.copy(Path(web_package.__file__).parent / "app.py", web_dir / "app.py")
    for folder in set(_DASHBOARD_FOLDERS) - {missing}:
        (web_dir / folder).mkdir()
    monkeypatch.setattr(web_package, "__path__", [str(web_dir), *web_package.__path__])
    _uncache_module(monkeypatch, "solar_challenge.web.app")


@pytest.mark.parametrize(
    "module",
    [
        "solar_challenge.web.jobs",
        "solar_challenge.web.routes",
        "solar_challenge.web.history",
        "solar_challenge.web.scenarios",
        "solar_challenge.web.api",
        "solar_challenge.web.assistant",
    ],
    ids=lambda module: module.rpartition(".")[2],
)
def test_building_the_app_fails_when_a_module_it_wires_in_cannot_import(
    module: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A job-manager or blueprint module that cannot import fails the app build instead of vanishing from the app."""
    # A None entry makes any import of the module raise ModuleNotFoundError naming it.
    monkeypatch.setitem(sys.modules, module, None)
    _uncache_module(monkeypatch, "solar_challenge.web.app")
    with pytest.raises(ImportError, match=re.escape(module)):
        build_test_app(tmp_path)


@pytest.mark.parametrize("missing", _DASHBOARD_FOLDERS)
def test_building_the_app_fails_naming_a_dashboard_folder_the_installed_package_lacks(
    missing: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An installed web package that lacks templates/ or static/ fails the app build with a FileNotFoundError naming the folder's path, and the build writes nothing into the package."""
    web_dir = tmp_path / "web"
    _import_app_from_a_web_package_lacking(missing, web_dir, monkeypatch)
    with pytest.raises(FileNotFoundError, match=re.escape(str(web_dir / missing))):
        build_test_app(tmp_path / "data")
    assert not (web_dir / missing).exists()


def test_building_the_app_does_not_import_the_anthropic_sdk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Building the app and serving the assistant page never import the anthropic SDK: the assistant imports it only to answer a chat."""
    monkeypatch.setitem(sys.modules, "anthropic", None)
    _uncache_module(monkeypatch, "solar_challenge.web.assistant")
    _uncache_module(monkeypatch, "solar_challenge.web.app")

    app = build_test_app(tmp_path)

    assert app.test_client().get("/assistant").status_code == 200


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """An empty home directory with no SECRET_KEY exported, so only a key persisted under it can supply one."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("SECRET_KEY", raising=False)
    return home_dir


def test_a_secret_key_in_test_config_leaves_the_home_directory_untouched(
    home: Path, tmp_path: Path
) -> None:
    """A SECRET_KEY supplied in test_config becomes the app's key, and the build never touches the key persisted under the home directory."""
    app = build_test_app(tmp_path / "data", secret_key="a-key-from-test-config")

    assert app.secret_key == "a-key-from-test-config"
    assert [path.name for path in home.iterdir()] == []


def test_without_a_supplied_secret_key_the_app_keeps_one_under_the_home_directory(
    home: Path, tmp_path: Path
) -> None:
    """With no SECRET_KEY in test_config or the environment, the app persists a generated key under the home directory and the next build reuses it."""
    first = build_test_app(tmp_path / "data", secret_key=None)
    second = build_test_app(tmp_path / "data", secret_key=None)

    key_file = home / ".solar-challenge" / ".secret_key"
    assert first.secret_key
    assert first.secret_key == second.secret_key == key_file.read_text()


@pytest.mark.parametrize("flask_debug", ["0", "1"], ids=["debug_off", "debug_on"])
def test_the_session_cookie_is_not_marked_secure(
    flask_debug: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The session cookie is not Secure, in debug mode or out of it: `solar-challenge web start` serves plain HTTP, also to the LAN with --host 0.0.0.0, and browsers withhold a Secure cookie from a non-localhost plain-HTTP origin, so the assistant would lose its chat session on every request."""
    monkeypatch.setenv("FLASK_DEBUG", flask_debug)
    app = build_test_app(tmp_path)
    client = app.test_client()

    assert client.get("/assistant/history").status_code == 200
    cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"])
    assert cookie is not None
    assert not cookie.secure

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_uv_env.py, the process environment in which a test runs a uv command."""

import os
import re
from pathlib import Path

import pytest

from tests._uv_env import SharedUvEnvironments, isolated_uv_env, uv_run_options

_CALLERS_VIRTUALENV_AND_LOCK_MODE = ["VIRTUAL_ENV", "UV_FROZEN", "UV_LOCKED", "UV_NO_SYNC"]

_DEV_ONLY_COMMANDS = [
    "uv run --locked --extra dev pytest tests/interpreter_matrix",
    "timeout -k 60 600 uv run --locked --extra dev pytest tests/integration/test_pvgis.py -p no:cacheprovider",
    "timeout -k 60 600 uv run --locked --extra dev pytest tests/css_build -p no:cacheprovider",
    "uv run --locked --extra dev pytest tests/newest_releases -p no:cacheprovider",
]

_DEV_AND_WEB_COMMANDS = [
    "uv run --locked --extra dev --extra web pytest -m 'not slow and not e2e' --ignore=tests/e2e",
    "uv run --locked --extra dev --extra web pytest tests/unit/test_web_app.py",
]

_DEV_WEB_AND_E2E_COMMAND = (
    "timeout -k 60 1800 uv run --locked --extra dev --extra web --extra e2e pytest tests/e2e -m 'not slow' "
    "-p no:cacheprovider"
)


def _project_environment(env: dict[str, str]) -> Path:
    return Path(env["UV_PROJECT_ENVIRONMENT"])


@pytest.mark.parametrize("name", _CALLERS_VIRTUALENV_AND_LOCK_MODE)
def test_the_callers_virtualenv_and_lock_mode_are_left_out(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name, "1")

    assert name not in isolated_uv_env(tmp_path / "venv")


def test_the_project_environment_is_the_one_given_not_the_callers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / "callers-venv"))

    assert isolated_uv_env(tmp_path / "venv")["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / "venv")


def test_every_other_variable_of_this_process_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """UV_PYTHON_INSTALL_DIR, for one, which a sandboxed caller sets so uv can install an interpreter."""
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(tmp_path / "pythons"))
    kept = {name: value for name, value in os.environ.items() if name not in _CALLERS_VIRTUALENV_AND_LOCK_MODE}

    assert isolated_uv_env(tmp_path / "venv") == {**kept, "UV_PROJECT_ENVIRONMENT": str(tmp_path / "venv")}


@pytest.mark.parametrize(
    ("command", "options"),
    [
        (
            "timeout -k 60 600 uv run --locked --extra dev pytest tests/css_build -p no:cacheprovider",
            ("--locked", "--extra", "dev"),
        ),
        (
            "uv run --locked --extra dev --extra web pytest -m 'not slow and not e2e' --ignore=tests/e2e",
            ("--locked", "--extra", "dev", "--extra", "web"),
        ),
    ],
    ids=["after-a-timeout-prefix", "before-quoted-pytest-arguments"],
)
def test_uv_run_options_are_the_words_between_uv_run_and_the_pytest_it_runs(
    command: str, options: tuple[str, ...]
) -> None:
    assert uv_run_options(command) == options


@pytest.mark.parametrize(
    "command",
    ["true", "uv run --locked --extra dev --extra web mypy src/solar_challenge", "pytest tests/unit"],
    ids=["no-uv-run", "no-pytest", "pytest-without-uv-run"],
)
def test_a_command_that_runs_no_pytest_through_uv_run_is_refused_by_name(command: str) -> None:
    with pytest.raises(AssertionError, match=re.escape(command)):
        uv_run_options(command)


def test_commands_giving_uv_run_the_same_options_share_one_environment_under_the_root(tmp_path: Path) -> None:
    """Whatever their timeout prefix or pytest arguments, in which the four dev-only lane jobs' commands differ."""
    environments = SharedUvEnvironments(tmp_path)

    shared = {_project_environment(environments.for_command(command)) for command in _DEV_ONLY_COMMANDS}

    assert len(shared) == 1, shared
    (project_environment,) = shared
    assert project_environment.is_relative_to(tmp_path) and project_environment != tmp_path


def test_commands_giving_uv_run_different_options_get_different_environments(tmp_path: Path) -> None:
    """`uv run` syncs inexactly, so an environment another command's extras synced into would hold more than this one names."""
    environments = SharedUvEnvironments(tmp_path)

    dev_only = _project_environment(environments.for_command(_DEV_ONLY_COMMANDS[0]))
    dev_and_web = _project_environment(environments.for_command(_DEV_AND_WEB_COMMANDS[0]))

    assert dev_only != dev_and_web


def test_the_probes_seven_commands_need_three_environments(tmp_path: Path) -> None:
    """One per set of uv run options: dev; dev and web; dev, web and e2e."""
    environments = SharedUvEnvironments(tmp_path)
    commands = [*_DEV_ONLY_COMMANDS, *_DEV_AND_WEB_COMMANDS, _DEV_WEB_AND_E2E_COMMAND]

    project_environments = {_project_environment(environments.for_command(command)) for command in commands}

    assert len(project_environments) == 3, project_environments


def test_for_command_builds_the_environment_from_this_process_at_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So each probe carries its own test's variables, such as its offline window's proxy variables, not another test's."""
    environments = SharedUvEnvironments(tmp_path / "environments")
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(tmp_path / "pythons"))
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "callers-venv"))
    monkeypatch.setenv("UV_FROZEN", "1")

    env = environments.for_command(_DEV_ONLY_COMMANDS[0])

    assert env["UV_PYTHON_INSTALL_DIR"] == str(tmp_path / "pythons")
    assert env == isolated_uv_env(_project_environment(env))

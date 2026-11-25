# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_orchestrator_config.py's verify_env and pytest_arguments.

verify_env reads a throwaway project's yaml; pytest_arguments reads an
OrchestratorCommand. tests/unit/test_orchestrator_config_helper.py tests the
module's other readers.
"""

from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

from tests._orchestrator_config import OrchestratorCommand, pytest_arguments, verify_env


def _write_orchestrator_config(project_root: Path, config: Mapping[str, object]) -> None:
    """Make *config* the whole of *project_root*'s dark-factory-orchestrator.yaml."""
    (project_root / "dark-factory-orchestrator.yaml").write_text(yaml.safe_dump(dict(config)), encoding="utf-8")


def _test_command(command: str, project_root: Path) -> OrchestratorCommand:
    """Return *command* as the verify's test command run in *project_root*."""
    return OrchestratorCommand(label="test_command", command=command, directory=project_root, role="task")


@pytest.mark.parametrize(
    "config",
    [
        pytest.param({"test_command": "pytest"}, id="no-verify-env-key"),
        pytest.param({"verify_env": None}, id="bare-verify-env-key"),
    ],
)
def test_a_yaml_without_a_verify_env_sets_no_variable(tmp_path: Path, config: Mapping[str, object]) -> None:
    _write_orchestrator_config(tmp_path, config)

    assert verify_env(tmp_path) == {}


def test_a_verify_env_of_string_values_is_read_whole(tmp_path: Path) -> None:
    env = {"PYTEST_XDIST_AUTO_NUM_WORKERS": "8", "UV_NO_PROGRESS": "1"}
    _write_orchestrator_config(tmp_path, {"verify_env": env})

    assert verify_env(tmp_path) == env


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({"PYTEST_XDIST_AUTO_NUM_WORKERS": 8}, id="unquoted-int-value"),
        pytest.param(["PYTEST_XDIST_AUTO_NUM_WORKERS=8"], id="list-not-mapping"),
    ],
)
def test_a_verify_env_that_is_not_a_mapping_of_strings_fails_naming_what_the_yaml_holds(
    tmp_path: Path, env: object
) -> None:
    _write_orchestrator_config(tmp_path, {"verify_env": env})

    with pytest.raises(AssertionError) as failure:
        verify_env(tmp_path)

    assert repr(env) in str(failure.value)


@pytest.mark.parametrize(
    ("command", "arguments"),
    [
        pytest.param("uv run --locked pytest -n 0 tests/unit", ("-n", "0", "tests/unit"), id="pytest-word"),
        pytest.param("python -m pytest tests/unit", ("tests/unit",), id="python-m-pytest"),
        pytest.param("uv run pytest -m 'not slow'", ("-m", "not slow"), id="quoted-argument-is-one-word"),
        pytest.param("uv run pytest", (), id="no-argument"),
    ],
)
def test_the_pytest_arguments_of_a_command_are_its_shell_words_after_its_first_pytest_word(
    tmp_path: Path, command: str, arguments: tuple[str, ...]
) -> None:
    assert pytest_arguments(_test_command(command, tmp_path)) == arguments


def test_a_command_that_runs_no_pytest_fails_naming_the_command(tmp_path: Path) -> None:
    command = _test_command("uv run --locked mypy src/solar_challenge", tmp_path)

    with pytest.raises(AssertionError, match="runs no pytest") as failure:
        pytest_arguments(command)

    assert command.label in str(failure.value)
    assert repr(command.command) in str(failure.value)

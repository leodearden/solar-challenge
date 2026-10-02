# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_orchestrator_config.py, the orchestrator contract tests' reader of dark-factory-orchestrator.yaml."""

import textwrap
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

from tests._orchestrator_config import (
    git_config,
    lane_job_directory,
    lane_job_enabled,
    sole_offline_lane_job,
)


def _write_orchestrator_config(project_root: Path, git: Mapping[str, object]) -> None:
    (project_root / "dark-factory-orchestrator.yaml").write_text(yaml.safe_dump({"git": git}), encoding="utf-8")


def test_the_git_mapping_is_read_whole_from_the_project_roots_orchestrator_config(tmp_path: Path) -> None:
    (tmp_path / "dark-factory-orchestrator.yaml").write_text(
        textwrap.dedent(
            """\
            test_command: "pytest"
            git:
              main_branch: "main"
              offline_lane_enabled: true
              offline_lane_commands:
                - name: probe
                  command: "pytest"
            """
        ),
        encoding="utf-8",
    )

    assert git_config(tmp_path) == {
        "main_branch": "main",
        "offline_lane_enabled": True,
        "offline_lane_commands": [{"name": "probe", "command": "pytest"}],
    }


def test_a_lane_job_named_once_is_returned_whole(tmp_path: Path) -> None:
    probe_job = {"name": "probe", "command": "pytest", "fix_task_priority": "medium"}
    _write_orchestrator_config(
        tmp_path, {"offline_lane_commands": [{"name": "e2e", "command": "pytest tests/e2e"}, probe_job]}
    )

    assert sole_offline_lane_job(tmp_path, "probe") == probe_job


@pytest.mark.parametrize(
    ("git", "count"),
    [
        pytest.param(
            {"offline_lane_commands": [{"name": "e2e", "command": "pytest tests/e2e"}]}, 0, id="no-job-named-probe"
        ),
        pytest.param({"offline_lane_commands": None}, 0, id="bare-offline-lane-commands-key"),
        pytest.param({"main_branch": "main"}, 0, id="no-offline-lane-commands-key"),
        pytest.param(
            {
                "offline_lane_commands": [
                    {"name": "probe", "command": "pytest"},
                    {"name": "probe", "command": "pytest tests/unit"},
                ]
            },
            2,
            id="two-jobs-named-probe",
        ),
    ],
)
def test_a_lane_job_named_other_than_once_fails_naming_the_job_and_its_count(
    tmp_path: Path, git: Mapping[str, object], count: int
) -> None:
    _write_orchestrator_config(tmp_path, git)

    with pytest.raises(AssertionError) as failure:
        sole_offline_lane_job(tmp_path, "probe")

    assert "'probe'" in str(failure.value)
    assert f"{count} entries" in str(failure.value)


def test_a_lane_job_without_a_cwd_runs_in_the_project_root(tmp_path: Path) -> None:
    job = {"name": "probe", "command": "pytest"}

    assert lane_job_directory(tmp_path, job) == tmp_path


def test_a_lane_job_with_a_cwd_runs_in_that_directory_under_the_project_root(tmp_path: Path) -> None:
    (tmp_path / "tests" / "e2e").mkdir(parents=True)
    job = {"name": "probe", "command": "pytest", "cwd": "tests/e2e"}

    assert lane_job_directory(tmp_path, job) == tmp_path / "tests" / "e2e"


@pytest.mark.parametrize("cwd", [None, ["tests", "e2e"]], ids=["bare-cwd-key", "list"])
def test_a_lane_job_whose_cwd_is_not_a_path_string_fails_naming_the_job_and_its_cwd(
    tmp_path: Path, cwd: object
) -> None:
    job = {"name": "probe", "command": "pytest", "cwd": cwd}

    with pytest.raises(AssertionError) as failure:
        lane_job_directory(tmp_path, job)

    assert "'probe'" in str(failure.value)
    assert repr(cwd) in str(failure.value)


def test_a_lane_job_whose_cwd_names_no_directory_fails_naming_the_job_and_its_cwd(tmp_path: Path) -> None:
    job = {"name": "probe", "command": "pytest", "cwd": "tests/e2e"}

    with pytest.raises(AssertionError) as failure:
        lane_job_directory(tmp_path, job)

    assert "'probe'" in str(failure.value)
    assert "'tests/e2e'" in str(failure.value)


def test_a_lane_job_without_an_enabled_flag_is_enabled() -> None:
    job = {"name": "probe", "command": "pytest"}

    assert lane_job_enabled(job) is True


@pytest.mark.parametrize("enabled", [True, False])
def test_a_lane_job_with_an_enabled_flag_is_enabled_as_the_flag_says(enabled: bool) -> None:
    job = {"name": "probe", "command": "pytest", "enabled": enabled}

    assert lane_job_enabled(job) is enabled


@pytest.mark.parametrize("enabled", [None, "false"], ids=["bare-enabled-key", "quoted-false"])
def test_a_lane_job_whose_enabled_flag_is_not_a_boolean_fails_naming_the_job_and_its_flag(
    enabled: object
) -> None:
    job = {"name": "probe", "command": "pytest", "enabled": enabled}

    with pytest.raises(AssertionError) as failure:
        lane_job_enabled(job)

    assert "'probe'" in str(failure.value)
    assert repr(enabled) in str(failure.value)

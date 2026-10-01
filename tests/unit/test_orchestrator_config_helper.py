# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_orchestrator_config.py, the orchestrator contract tests' reader of dark-factory-orchestrator.yaml."""

from pathlib import Path

import pytest

from tests._orchestrator_config import lane_job_directory


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

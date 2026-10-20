# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_verify_suite.py, the runner through which the offline-lane suites re-run the orchestrator verify suite.

Each test runs a throwaway project's test_command, plain sh, with no uv and no mocks.
That no process a hung suite started outlives it is pinned with every other probe's,
in test_command_runner_helper.py's test_no_process_a_hung_probe_started_outlives_it.
"""

import os
from pathlib import Path

import pytest
import yaml

from tests._verify_suite import run_verify_suite


def _project_with_test_command(project_root: Path, test_command: str) -> Path:
    """Make *project_root* a throwaway project whose orchestrator test_command is *test_command*."""
    (project_root / "dark-factory-orchestrator.yaml").write_text(
        yaml.safe_dump({"test_command": test_command}), encoding="utf-8"
    )
    return project_root


def test_runs_the_projects_test_command_verbatim_in_its_root_and_the_given_environment_as_a_task_verify(
    tmp_path: Path,
) -> None:
    """The given environment carries DF_VERIFY_ROLE=offline, as the interpreter-matrix lane job's does, yet the suite runs as a task verify."""
    (tmp_path / "marker.txt").write_text("in-the-project-root", encoding="utf-8")
    project = _project_with_test_command(
        tmp_path,
        'cat marker.txt; echo "probe=$VERIFY_SUITE_PROBE role=$DF_VERIFY_ROLE"; echo on-stderr >&2; exit 3',
    )

    result = run_verify_suite(
        project, {**os.environ, "VERIFY_SUITE_PROBE": "given", "DF_VERIFY_ROLE": "offline"}, variant="in a probe"
    )

    assert result.returncode == 3
    assert "in-the-project-root" in result.stdout
    assert "probe=given role=task" in result.stdout
    assert "on-stderr" in result.stderr


def test_a_hung_suite_fails_the_calling_test_naming_the_variant_and_the_output_so_far(tmp_path: Path) -> None:
    project = _project_with_test_command(tmp_path, "echo started; sleep 30")

    with pytest.raises(pytest.fail.Exception) as failure:
        run_verify_suite(project, os.environ, variant="in a probe", timeout_secs=1)

    assert "the verify suite in a probe hung for 1 s" in str(failure.value)
    assert "started" in str(failure.value)

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_verify_suite.py, the runner through which the offline-lane suites re-run the orchestrator verify suite.

Each test runs a throwaway project's test_command, plain sh, with no uv and no mocks.
"""

import os
import shlex
import time
from pathlib import Path

import pytest
import yaml

from tests._verify_suite import output_tail, run_verify_suite


def _project_with_test_command(project_root: Path, test_command: str) -> Path:
    """Make *project_root* a throwaway project whose orchestrator test_command is *test_command*."""
    (project_root / "dark-factory-orchestrator.yaml").write_text(
        yaml.safe_dump({"test_command": test_command}), encoding="utf-8"
    )
    return project_root


def test_runs_the_projects_test_command_verbatim_in_its_root_and_the_given_environment(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("in-the-project-root", encoding="utf-8")
    project = _project_with_test_command(
        tmp_path, 'cat marker.txt; echo "probe=$VERIFY_SUITE_PROBE"; echo on-stderr >&2; exit 3'
    )

    result = run_verify_suite(project, {**os.environ, "VERIFY_SUITE_PROBE": "given"}, variant="in a probe")

    assert result.returncode == 3
    assert "in-the-project-root" in result.stdout
    assert "probe=given" in result.stdout
    assert "on-stderr" in result.stdout


def test_a_hung_suite_fails_the_calling_test_naming_the_variant_and_the_output_so_far(tmp_path: Path) -> None:
    project = _project_with_test_command(tmp_path, "echo started; sleep 30")

    with pytest.raises(pytest.fail.Exception) as failure:
        run_verify_suite(project, os.environ, variant="in a probe", timeout_secs=1)

    assert "the verify suite in a probe hung for 1 s" in str(failure.value)
    assert "started" in str(failure.value)


def test_no_process_the_suite_started_outlives_a_hang(tmp_path: Path) -> None:
    survivor = tmp_path / "survived"
    project = _project_with_test_command(tmp_path, f"(sleep 2; touch {shlex.quote(str(survivor))}) & sleep 30")

    with pytest.raises(pytest.fail.Exception):
        run_verify_suite(project, os.environ, variant="in a probe", timeout_secs=0.5)
    time.sleep(3)

    assert not survivor.exists(), (
        "a process the suite started outlived the hang, so a hung suite would keep running after the case "
        "that started it ends"
    )


def test_output_tail_keeps_the_end_of_a_long_output_and_all_of_a_short_one() -> None:
    assert output_tail("short") == "short"

    tail = output_tail("HEAD" + "x" * 100_000 + "END")

    assert tail.endswith("END")
    assert "HEAD" not in tail

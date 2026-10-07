# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_verify_suite.py, the runner through which the offline-lane suites re-run the orchestrator verify suite.

Each test runs a throwaway project's test_command, plain sh, with no uv and no mocks.
"""

import os
import shlex
import signal
import time
from pathlib import Path

import pytest
import yaml

from tests._verify_suite import output_tail, run_verify_suite

# Each hang outlasts the one before, so a shell that the host's load starts slowly still starts its background
# child before the kill.
_HANG_TIMEOUTS_SECS = (0.5, 2.0, 8.0)


def _project_with_test_command(project_root: Path, test_command: str) -> Path:
    """Make *project_root* a throwaway project whose orchestrator test_command is *test_command*."""
    (project_root / "dark-factory-orchestrator.yaml").write_text(
        yaml.safe_dump({"test_command": test_command}), encoding="utf-8"
    )
    return project_root


def _pid_of_a_background_child_killed_in_a_hang(tmp_path: Path) -> int:
    """Hang a suite whose shell starts a long-lived child in the background, until the hang is killed; return the child's pid.

    The shell hangs in a shorter sleep of its own, and the child writes to
    /dev/null rather than to the suite's output. So the hang ends while the
    child still runs, even when the kill misses the child.
    """
    pid_file = tmp_path / "background.pid"
    part, whole = shlex.quote(f"{pid_file}.part"), shlex.quote(str(pid_file))
    # The rename makes the pid file appear whole or not at all, wherever the kill interrupts the shell.
    project = _project_with_test_command(
        tmp_path, f"sleep 120 >/dev/null 2>&1 & echo $! > {part} && mv {part} {whole}; sleep 30"
    )
    for timeout_secs in _HANG_TIMEOUTS_SECS:
        with pytest.raises(pytest.fail.Exception):
            run_verify_suite(project, os.environ, variant="in a probe", timeout_secs=timeout_secs)
        if pid_file.exists():
            return int(pid_file.read_text(encoding="utf-8"))
    pytest.fail(f"the probe's shell started no background child in hangs of {_HANG_TIMEOUTS_SECS} s")


def _process_exists(pid: int) -> bool:
    """Return whether a process *pid* exists, a zombie included."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone_within(pid: int, seconds: float) -> bool:
    """Return whether the process *pid* is gone, ended and reaped, within *seconds*."""
    deadline = time.monotonic() + seconds
    while _process_exists(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


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
    background_pid = _pid_of_a_background_child_killed_in_a_hang(tmp_path)

    outlived = not _gone_within(background_pid, seconds=10)
    if outlived:
        os.kill(background_pid, signal.SIGKILL)

    assert not outlived, (
        f"process {background_pid}, which the suite started in the background, outlived the hang, so a hung "
        "suite would keep running after the case that started it ends"
    )


def test_output_tail_keeps_the_end_of_a_long_output_and_all_of_a_short_one() -> None:
    assert output_tail("short") == "short"

    tail = output_tail("HEAD" + "x" * 100_000 + "END")

    assert tail.endswith("END")
    assert "HEAD" not in tail

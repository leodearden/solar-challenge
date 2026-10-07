# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Run the orchestrator verify suite verbatim, as the orchestrator runs it.

It serves the offline-lane suites that re-run the verify suite under one
variation, such as another interpreter or newer dependency releases.

Usage::

    from tests._verify_suite import output_tail, run_verify_suite

    result = run_verify_suite(project_root, env, variant="on Python 3.13")
    assert result.returncode == 0, f"... output tail:\n{output_tail(result.stdout)}"
"""

import contextlib
import os
import signal
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from tests._orchestrator_config import load_orchestrator_config

# About 15x the slowest measured suite run (491 s on 3.11). It exists only so a
# hang cannot stall the single-flight offline lane forever.
_SUITE_TIMEOUT_SECS = 7200

# Enough of the suite's output to carry pytest's short test summary.
_OUTPUT_TAIL_CHARS = 5000


def _kill_process_group(proc: subprocess.Popen[str]) -> None:
    """SIGKILL *proc*'s whole process group, unless *proc* has already been reaped.

    Until Popen reaps *proc*, its pid, which is also the group's id, cannot be reused.
    """
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)


def output_tail(output: str) -> str:
    """Return the last _OUTPUT_TAIL_CHARS characters of the suite's *output*, for a failure message."""
    return output[-_OUTPUT_TAIL_CHARS:]


def run_verify_suite(
    project_root: Path, env: Mapping[str, str], *, variant: str, timeout_secs: float = _SUITE_TIMEOUT_SECS
) -> subprocess.CompletedProcess[str]:
    """Run *project_root*'s orchestrator test_command verbatim there, in *env*, as the orchestrator runs it.

    *variant* says how this run differs from the per-task verify, e.g. "on Python
    3.13", for the failure a hang raises.

    The suite runs in a session of its own, which no signal sent to this process
    reaches. If the case ends before the suite does (a hang, an interrupt, an
    error), the whole process group is killed, so uv, pytest and its workers do
    not outlive the case.
    """
    command = load_orchestrator_config(project_root)["test_command"]
    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = proc.communicate(timeout=timeout_secs)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        output, _ = proc.communicate()
        pytest.fail(
            f"the verify suite {variant} hung for {timeout_secs} s and was killed; "
            f"output tail:\n{output_tail(output)}"
        )
    finally:
        _kill_process_group(proc)
    return subprocess.CompletedProcess(command, proc.returncode, output)

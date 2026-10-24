# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Run the orchestrator verify suite verbatim, as the orchestrator runs it.

It serves the offline-lane suites that re-run the verify suite under one
variation, such as another interpreter or newer dependency releases.

Usage::

    from tests._command_runner import describe_pytest_outcome
    from tests._verify_suite import run_verify_suite

    result = run_verify_suite(project_root, env, variant="on Python 3.13")
    assert result.returncode == 0, f"the verify suite failed on Python 3.13\n{describe_pytest_outcome(result)}"
"""

from collections.abc import Mapping
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from tests._command_runner import CommandTimedOut, run_command
from tests._orchestrator_config import verify_command

# About 15x the slowest measured suite run (491 s on 3.11). It exists only so a
# hang cannot stall the single-flight offline lane forever.
_SUITE_TIMEOUT_SECS = 7200


def run_verify_suite(
    project_root: Path, env: Mapping[str, str], *, variant: str, timeout_secs: float = _SUITE_TIMEOUT_SECS
) -> CompletedProcess[str]:
    """Run *project_root*'s orchestrator test_command verbatim there, in *env*, as a task verify runs it.

    *variant* says how this run differs from the per-task verify, e.g. "on Python
    3.13", for the failure a hang raises. The suite runs through run_command, so a
    hang, an interrupt or an error that ends the case before the suite does leaves
    none of the processes it started, uv, pytest and its workers, running.
    """
    try:
        return run_command(verify_command(project_root, "test_command"), env, timeout_secs=timeout_secs)
    except CommandTimedOut as timed_out:
        pytest.fail(f"the verify suite {variant} hung for {timeout_secs} s and was killed: {timed_out}")

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract tests only the offline lane's e2e job keeps.

tests/unit/test_offline_lane_contracts.py holds the contracts every lane job
keeps, and a test only one job needs stays in that job's module. These read the
e2e job's steps from dark-factory-orchestrator.yaml: they run no uv and reach no
network.
"""

import shlex
from collections.abc import Sequence
from pathlib import Path

from tests._orchestrator_config import OrchestratorCommand, lane_job_steps
from tests._uv_env import uv_run_options

_E2E_JOB = "e2e"

_BROWSER_INSTALL = ("playwright", "install")

_BROWSER = "chromium-headless-shell"

_SKIP_BROWSER_GC = "PLAYWRIGHT_SKIP_BROWSER_GC=1"


def _holds_run(words: Sequence[str], run: Sequence[str]) -> bool:
    """Whether *run* is a contiguous run of *words*."""
    return any(tuple(words[start : start + len(run)]) == tuple(run) for start in range(len(words) - len(run) + 1))


def _browser_install_steps(project_root: Path) -> list[OrchestratorCommand]:
    """Return the e2e job's setup steps that run `playwright install`, in order."""
    return [
        step
        for step in lane_job_steps(project_root, _E2E_JOB).setup
        if _holds_run(shlex.split(step.command), _BROWSER_INSTALL)
    ]


def _is_assignment(word: str) -> bool:
    """Whether sh reads *word*, at the start of a command, as a variable assignment: a name, `=`, then its value."""
    name, equals, _ = word.partition("=")
    return bool(equals) and name.isidentifier()


def _installer_environment(words: Sequence[str]) -> Sequence[str]:
    """Return a step's leading words that set the environment its command runs in: shell assignments, and `env` with those it passes on.

    The first word that is neither, such as `timeout`, is the command, and an
    assignment after it is that command's argument, which `timeout` runs as a
    program, not a variable.
    """
    for index, word in enumerate(words):
        if word != "env" and not _is_assignment(word):
            return words[:index]
    return words


def test_the_e2e_job_installs_the_browser_its_suite_launches_before_running_it(project_root: Path) -> None:
    steps = lane_job_steps(project_root, _E2E_JOB)
    expected = ("uv", "run", *uv_run_options(steps.suite.command), *_BROWSER_INSTALL, _BROWSER)

    assert any(_holds_run(shlex.split(step.command), expected) for step in steps.setup), (
        f"no setup step of the {steps.suite.label} runs {shlex.join(expected)!r} before its suite step "
        f"{steps.suite.command!r}, so once the browser its playwright needs is missing, every e2e test ERRORs with "
        "\"Executable doesn't exist\"; docs/orchestrator-config.md §8 says why the job installs it"
    )


def test_the_e2e_jobs_browser_install_deletes_no_browser_of_another_install(project_root: Path) -> None:
    installs = _browser_install_steps(project_root)
    assert installs, (
        f"no setup step of the lane job {_E2E_JOB!r} runs `{shlex.join(_BROWSER_INSTALL)}`, so there is no browser "
        "install to check"
    )

    unguarded = [
        install.command
        for install in installs
        if _SKIP_BROWSER_GC not in _installer_environment(shlex.split(install.command))
    ]
    assert not unguarded, (
        f"the browser installs {unguarded} of the lane job {_E2E_JOB!r} do not set {_SKIP_BROWSER_GC} in the "
        "installer's environment, so each deletes other installs' browsers; set it as a shell assignment or through "
        "`env` at the start of the step; docs/orchestrator-config.md §8 says why"
    )

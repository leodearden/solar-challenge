# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contract tests only the offline lane's e2e job keeps.

tests/unit/test_offline_lane_contracts.py holds the contracts every lane job
keeps, and a test only one job needs stays in that job's module. These read the
e2e job's steps from dark-factory-orchestrator.yaml, and one also collects the
job's suite step as the lane runs it, through uv, offline, as the lane contract
probes do.
"""

import shlex
from collections.abc import Sequence
from pathlib import Path

import pytest

from tests._collect_only import requires_uv
from tests._coreutils_timeout import timeout_secs
from tests._lane_collection import collect_lane_job
from tests._orchestrator_config import OrchestratorCommand, lane_job_steps
from tests._uv_env import SharedUvEnvironments, uv_run_options

_E2E_JOB = "e2e"

_BROWSER_INSTALL = ("playwright", "install")

_BROWSER = "chromium-headless-shell"

_SKIP_BROWSER_GC = "PLAYWRIGHT_SKIP_BROWSER_GC=1"

# The per-test budget of a serial lane run at idle priority on a loaded host: the measured mean, with headroom.
_SERIAL_BUDGET_SECS_PER_TEST = 15


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


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
def test_the_e2e_suite_steps_timeout_gives_each_test_it_collects_a_loaded_hosts_serial_budget(
    project_root: Path, shared_uv_probe_environments: SharedUvEnvironments
) -> None:
    collection = collect_lane_job(project_root, _E2E_JOB, env_for=shared_uv_probe_environments.for_command)
    suite = lane_job_steps(project_root, _E2E_JOB).suite
    collected = len(collection.node_ids())
    budget = collected * _SERIAL_BUDGET_SECS_PER_TEST
    bound = timeout_secs(suite)

    assert bound >= budget, (
        f"the suite step of the {suite.label}, {suite.command!r}, is bounded at {bound:g} s, less than the serial "
        f"budget of the {collected} tests it collects, {_SERIAL_BUDGET_SECS_PER_TEST} s each, {budget} s. Run "
        "serially at the lane's idle priority on a loaded host, the suite can then be killed while still green, "
        "before pytest reports, and the lane files e2e::nonzero-exit, unconfirmable, naming no test. Raise the "
        "step's `timeout` in dark-factory-orchestrator.yaml; the running lane reads the raise only once the "
        "orchestrator reloads its config"
    )

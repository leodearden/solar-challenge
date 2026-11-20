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


def _words_before_the_installer(words: Sequence[str]) -> Sequence[str]:
    """Return an install step's words before its first `uv` or `playwright`, those that set the installer's environment."""
    starts = [index for index, word in enumerate(words) if word in ("uv", "playwright")]
    return words[: starts[0]] if starts else words


def test_the_e2e_job_installs_the_browser_its_suite_launches_before_running_it(project_root: Path) -> None:
    steps = lane_job_steps(project_root, _E2E_JOB)
    expected = ("uv", "run", *uv_run_options(steps.suite.command), *_BROWSER_INSTALL, _BROWSER)

    assert any(_holds_run(shlex.split(step.command), expected) for step in steps.setup), (
        f"no setup step of the {steps.suite.label} runs {shlex.join(expected)!r} before its suite step "
        f"{steps.suite.command!r}. Another project's `playwright install` deletes every browser in "
        "~/.cache/ms-playwright that no still-present install registered, and every environment this project "
        "registers one from is temporary; a uv.lock move of playwright needs a revision nobody has installed. "
        "Either way every e2e test then ERRORs with \"Executable doesn't exist\". The lane may write that cache and "
        "reach the download host, and the suite's own uv run options make the install the suite's own playwright, "
        "in its one environment; docs/orchestrator-config.md §8 says why"
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
        if _SKIP_BROWSER_GC not in _words_before_the_installer(shlex.split(install.command))
    ]
    assert not unguarded, (
        f"the browser installs {unguarded} of the lane job {_E2E_JOB!r} do not set {_SKIP_BROWSER_GC} before the "
        "installer starts, so each deletes every browser in ~/.cache/ms-playwright that no still-present install "
        "registered, other projects' included: the very failure this job's install exists to survive; set it as a "
        "shell assignment or through `env` ahead of the install's `uv run`"
    )

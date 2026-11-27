# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to dark-factory-orchestrator.yaml for the orchestrator contract tests.

Each command the yaml names is read as an OrchestratorCommand value: what it
runs, where, and in which DF_VERIFY_ROLE.

Usage::

    from tests._orchestrator_config import (
        VERIFY_SLOTS,
        git_config,
        lane_command,
        lane_commands,
        lane_job_steps,
        lane_jobs_declaring_an_outage_probe,
        lane_outage_probe,
        offline_lane_jobs,
        pytest_arguments,
        verify_command,
        verify_env,
    )

    test_command = verify_command(project_root, "test_command")
    test_command_pytest_arguments = pytest_arguments(test_command)
    worker_cap = verify_env(project_root).get("PYTEST_XDIST_AUTO_NUM_WORKERS")
    verify_commands = [verify_command(project_root, slot) for slot in VERIFY_SLOTS]
    e2e_job = lane_command(project_root, "e2e")
    e2e_suite_step = lane_job_steps(project_root, "e2e").suite
    pvgis_outage_probe = lane_outage_probe(project_root, "pvgis")
    probed_lane_jobs = lane_jobs_declaring_an_outage_probe(project_root)
    every_lane_job = lane_commands(project_root)
    offline_lane_enabled = git_config(project_root).get("offline_lane_enabled")
    lane_job_names = [job["name"] for job in offline_lane_jobs(project_root)]
"""

import os
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, get_args

import yaml

from tests._command_runner import VerifyRole

VerifySlot = Literal["lint_command", "type_check_command", "test_command"]

VERIFY_SLOTS: tuple[VerifySlot, ...] = get_args(VerifySlot)

_STEP_SEPARATOR = "&&"

_SHELL_OPERATOR_CHARACTERS = "();<>|&\n"

_SHELL_BLANKS = " \t"


@dataclass(frozen=True)
class OrchestratorCommand:
    """A command dark-factory-orchestrator.yaml names, as the orchestrator runs it.

    label is what failure messages call it, e.g. "test_command" or "lane job 'e2e'";
    command is the yaml string, verbatim; directory is where the orchestrator runs
    it, the project root standing in for the worktree's root; and role is the
    DF_VERIFY_ROLE dark-factory sets for it.
    """

    label: str
    command: str
    directory: Path
    role: VerifyRole

    def __post_init__(self) -> None:
        assert self.directory.is_dir(), (
            f"the {self.label} runs in {self.directory}, which is not a directory, so its command cannot start there"
        )


@dataclass(frozen=True)
class LaneJobSteps:
    """An offline-lane job's command, read as the steps `sh -c` runs in turn, each only if the one before succeeded.

    Each step is its text in the command, its words as shlex.join quotes them,
    run in the job's directory and role. The setup steps provision, as the e2e
    job's browser install does, and never collect. The suite step, the last, is
    the one pytest run, which the lane contract probes model the job by; it keeps
    the job's label, so a failure about the suite it collects names the job.
    """

    setup: tuple[OrchestratorCommand, ...]
    suite: OrchestratorCommand


def verify_command(project_root: Path, slot: VerifySlot) -> OrchestratorCommand:
    """Return the verify slot *slot* of *project_root*'s yaml, run in *project_root* as a task verify runs it."""
    assert slot in VERIFY_SLOTS, f"{slot!r} is not a dark-factory verify slot; those are {VERIFY_SLOTS}"
    command = _load_orchestrator_config(project_root).get(slot)
    assert isinstance(command, str), (
        f"dark-factory-orchestrator.yaml's verify slot {slot!r} is {command!r} (None if the yaml lacks it), "
        "not a command string"
    )
    return OrchestratorCommand(label=slot, command=command, directory=project_root, role="task")


def verify_env(project_root: Path) -> dict[str, str]:
    """Return the top-level `verify_env` mapping of *project_root*'s yaml, the variables dark-factory sets for every verify command; {} when the yaml has none.

    It asserts, naming what it found, that the value is a mapping of strings to
    strings, as dark-factory reads it.
    """
    env = _load_orchestrator_config(project_root).get("verify_env")
    if env is None:
        return {}
    assert isinstance(env, dict) and all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()), (
        f"dark-factory-orchestrator.yaml's verify_env is {env!r}, not a mapping of variable names to string values; "
        "quote each value, as in PYTEST_XDIST_AUTO_NUM_WORKERS: \"8\""
    )
    return dict(env)


def pytest_arguments(command: OrchestratorCommand) -> tuple[str, ...]:
    """Return the words *command* passes pytest: its shell words, as shlex.split reads them, after its first `pytest` word.

    It asserts, naming the command, that the command holds a `pytest` word.
    """
    words = shlex.split(command.command)
    assert "pytest" in words, f"the {command.label} {command.command!r} runs no pytest"
    return tuple(words[words.index("pytest") + 1 :])


def lane_command(project_root: Path, name: str) -> OrchestratorCommand:
    """Return the offline-lane job *name* of *project_root*'s yaml as the lane runs it, *project_root* standing in for the lane worktree's root.

    The rules are dark-factory's LaneCommand (orchestrator/src/orchestrator/config.py):
    the lane runs the command with `sh -c` in <worktree>/<cwd>, cwd defaulting to
    '.', and skips the job unless it is enabled, which it is by default. It asserts
    the job is the only one of its name, its cwd a path string and its enabled flag
    a YAML boolean that is true, so a job the lane would not run as named fails
    here, naming the job.
    """
    job = _sole_offline_lane_job(project_root, name)
    label = f"lane job {name!r}"
    enabled = job.get("enabled", True)
    assert isinstance(enabled, bool), (
        f"the enabled flag of the {label} is {enabled!r}, not a YAML boolean; dark-factory rejects some such "
        "values and coerces others, so write true or false"
    )
    assert enabled, f"the {label} is disabled, so the lane never runs it"
    cwd = job.get("cwd", ".")
    assert isinstance(cwd, str), f"the cwd of the {label} is {cwd!r}, not a path string, so dark-factory rejects it"
    return OrchestratorCommand(label=label, command=job["command"], directory=project_root / cwd, role="offline")


def lane_job_steps(project_root: Path, name: str) -> LaneJobSteps:
    """Return the offline-lane job *name* of *project_root*'s yaml, as lane_command builds it, split into its steps at each `&&` outside quotes.

    It asserts, naming the job and its command, that `&&` is the only shell
    operator the command holds, a line break counting as one; that no step is
    empty; that the command is spelled as its steps' words re-quoted with
    shlex.join, the spelling the probes run; and that the last step runs pytest
    and no other step does. So a command the steps cannot model fails here
    rather than being collected wrongly.
    """
    job = lane_command(project_root, name)
    steps = _words_of_each_step(job)
    _assert_spelled_as_its_steps(job, steps)
    *setup_words, suite_words = steps
    assert "pytest" in suite_words, (
        f"the last step of the {job.label} {job.command!r} runs no pytest, though the lane contract probes collect "
        "the job by that step; run the job's suite last"
    )
    setup_steps_running_pytest = [number for number, words in enumerate(setup_words, start=1) if "pytest" in words]
    assert not setup_steps_running_pytest, (
        f"the {job.label} {job.command!r} runs pytest in its setup steps {setup_steps_running_pytest}, though the "
        "lane contract probes collect only its last step, so the tests those steps run go unchecked; run pytest in "
        "the last step alone"
    )
    return LaneJobSteps(
        setup=tuple(
            replace(job, label=f"setup step {number} of the {job.label}", command=shlex.join(words))
            for number, words in enumerate(setup_words, start=1)
        ),
        suite=replace(job, command=shlex.join(suite_words)),
    )


def _words_of_each_step(job: OrchestratorCommand) -> list[list[str]]:
    """Return the shell words of each step of *job*'s command, in order, the steps split at each `&&` outside quotes.

    It asserts, naming the job and its command, that no other shell operator is
    among the words and that no step is empty.
    """
    words = _shell_words(job.command)
    other_operators = sorted({word for word in words if _is_shell_operator(word) and word != _STEP_SEPARATOR})
    assert not other_operators, (
        f"the {job.label} {job.command!r} holds shell operators other than {_STEP_SEPARATOR!r}: "
        f"{', '.join(map(repr, other_operators))}; the lane runs it whole with `sh -c`, but its steps are read as "
        f"joined by {_STEP_SEPARATOR!r} alone, so the lane contract probes would model it wrongly; write it on one "
        f"line as steps joined by {_STEP_SEPARATOR!r} alone"
    )
    steps: list[list[str]] = [[]]
    for word in words:
        if word == _STEP_SEPARATOR:
            steps.append([])
        else:
            steps[-1].append(word)
    assert all(steps), (
        f"the {job.label} {job.command!r} has an empty step, which sh refuses as a syntax error; give each "
        f"{_STEP_SEPARATOR!r} a command on either side"
    )
    return steps


def _shell_words(command: str) -> list[str]:
    """Return *command*'s words, split at sh's blanks and around its operator characters, a line break among them, never inside quotes.

    Like shlex.split, it reads no `#` as a comment, so a `#` stays in its word.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_SHELL_OPERATOR_CHARACTERS)
    lexer.whitespace = _SHELL_BLANKS
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _is_shell_operator(word: str) -> bool:
    """Whether *word* is a shell operator: a word made only of the operator characters _shell_words splits words around."""
    return bool(word) and set(word) <= set(_SHELL_OPERATOR_CHARACTERS)


def _assert_spelled_as_its_steps(job: OrchestratorCommand, steps: Sequence[Sequence[str]]) -> None:
    """Assert, naming *job* and its command, that the command is its *steps*' words re-quoted with shlex.join, joined by `&&`.

    The probes run each step so re-quoted. Spelled so in the yaml too, each step
    is its own text in the command, which sh reads alike in the lane and in a probe.
    """
    re_quoted = f" {_STEP_SEPARATOR} ".join(map(shlex.join, steps))
    parting = len(os.path.commonprefix([job.command, re_quoted]))
    assert job.command == re_quoted, (
        f"the {job.label} {job.command!r} is not spelled as its steps' words re-quoted with shlex.join, "
        f"{re_quoted!r}, the spelling the lane contract probes run. They part at {job.command[parting:]!r}, where "
        "sh may read the yaml's spelling otherwise, e.g. expanding a $, a backquote, a leading ~ or a glob, or "
        "reading a # as a comment. Spell the command as re-quoted, where sh reads that as the lane should run it"
    )


def lane_outage_probe(project_root: Path, name: str) -> OrchestratorCommand:
    """Return the outage probe the offline-lane job *name* of *project_root*'s yaml declares, as the lane runs it after a red run of the job.

    The rules are dark-factory's LaneCommand.outage_probe: the lane runs it with
    `sh -c` in the job's directory, in the job's offline role. It asserts the job
    passes lane_command's checks and declares its probe as a command string, so a
    job whose outages the lane would file as fix tasks fails here, naming the job.
    """
    job = lane_command(project_root, name)
    probe = _declared_outage_probe(_sole_offline_lane_job(project_root, name))
    assert isinstance(probe, str) and probe.strip(), (
        f"the {job.label} declares outage_probe {probe!r} (None if it declares none), not a command string, so the "
        "lane files a fix task for every outage of the service its tests use"
    )
    return replace(job, label=f"outage probe of the {job.label}", command=probe)


def lane_jobs_declaring_an_outage_probe(project_root: Path) -> tuple[str, ...]:
    """Return, in config order, the names of *project_root*'s offline-lane jobs that declare an outage probe of any value but None."""
    return tuple(job["name"] for job in offline_lane_jobs(project_root) if _declared_outage_probe(job) is not None)


def _declared_outage_probe(job: Mapping[str, Any]) -> object:
    """Return the outage_probe the offline-lane job *job* (a git.offline_lane_commands entry) declares, None if it declares none."""
    return job.get("outage_probe")


def lane_commands(project_root: Path) -> tuple[OrchestratorCommand, ...]:
    """Return every offline-lane job of *project_root*'s yaml as lane_command builds it, in config order."""
    return tuple(lane_command(project_root, job["name"]) for job in offline_lane_jobs(project_root))


def _load_orchestrator_config(project_root: Path) -> dict[str, Any]:
    """Return *project_root*'s dark-factory-orchestrator.yaml, parsed as YAML."""
    config_path = project_root / "dark-factory-orchestrator.yaml"
    config: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return config


def git_config(project_root: Path) -> dict[str, Any]:
    """Return the `git` mapping (dark-factory's GitConfig) of *project_root*'s dark-factory-orchestrator.yaml, where the offline-lane settings live."""
    git: dict[str, Any] = _load_orchestrator_config(project_root)["git"]
    return git


def offline_lane_jobs(project_root: Path) -> list[dict[str, Any]]:
    """Return *project_root*'s offline-lane jobs (git.offline_lane_commands entries) in config order; none when that key is absent or empty."""
    jobs: list[dict[str, Any]] = git_config(project_root).get("offline_lane_commands") or []
    return jobs


def _sole_offline_lane_job(project_root: Path, name: str) -> dict[str, Any]:
    """Return the offline-lane job (git.offline_lane_commands entry) named *name*, asserting it is the only one."""
    jobs = [job for job in offline_lane_jobs(project_root) if job.get("name") == name]
    assert len(jobs) == 1, (
        f"git.offline_lane_commands has {len(jobs)} entries named {name!r}; with none the lane "
        "never runs that job, with several every merge runs it more than once"
    )
    return jobs[0]

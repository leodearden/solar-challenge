# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one runner through which the orchestrator contract tests start a command, and the one description of how it ended.

run_command starts a command as the orchestrator does: verbatim through `sh -c`,
in the command's directory, with the DF_VERIFY_ROLE dark-factory sets for an
OrchestratorCommand. The command runs in a session of its own, and no process in
that session outlives a hang: at its timeout, every one of them is killed.

Usage::

    from tests._command_runner import CommandTimedOut, ShellCommand, describe_outcome, run_command
    from tests._orchestrator_config import verify_command

    result = run_command(verify_command(project_root, "test_command"), env, timeout_secs=600)
    assert result.returncode == 0, describe_outcome(result)
    version = run_command(ShellCommand("uv --version", project_root), timeout_secs=60)
"""

import contextlib
import os
import signal
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tests._orchestrator_config import OrchestratorCommand

_STREAM_TAIL_CHARS = 5000

_DRAIN_AFTER_KILL_SECS = 5


@dataclass(frozen=True)
class ShellCommand:
    """A shell command that no dark-factory-orchestrator.yaml names, run in *directory*; it has no DF_VERIFY_ROLE of its own."""

    command: str
    directory: Path

    def __post_init__(self) -> None:
        assert self.directory.is_dir(), (
            f"the shell command {self.command!r} runs in {self.directory}, which is not a directory, so it cannot "
            "start there"
        )


class Outcome(Protocol):
    """How a run ended: its exit code and what it printed to each stream."""

    @property
    def returncode(self) -> int: ...

    @property
    def stdout(self) -> str: ...

    @property
    def stderr(self) -> str: ...


def _tails(stdout: str, stderr: str) -> str:
    """Return the tail of each stream, so a long stderr, such as uv's log, cannot crowd out the end of stdout."""
    return f"stdout tail:\n{stdout[-_STREAM_TAIL_CHARS:]}\nstderr tail:\n{stderr[-_STREAM_TAIL_CHARS:]}"


def describe_outcome(outcome: Outcome) -> str:
    """Describe how *outcome*'s run ended, for an assertion message: its exit code, then the tail of each stream."""
    return f"exit {outcome.returncode}\n{_tails(outcome.stdout, outcome.stderr)}"


class CommandTimedOut(Exception):
    """A command was still running at its timeout, so it was killed with every process in its session.

    It holds the command, the directory it ran in, its timeout, and what it printed
    to each stream before it was killed.
    """

    def __init__(self, command: str, directory: Path, timeout_secs: float, stdout: str, stderr: str) -> None:
        super().__init__(
            f"{command!r} in {directory} was still running after {timeout_secs} s, so it was killed with every "
            f"process in its session\n{_tails(stdout, stderr)}"
        )
        self.command = command
        self.directory = directory
        self.timeout_secs = timeout_secs
        self.stdout = stdout
        self.stderr = stderr


def run_command(
    command: OrchestratorCommand | ShellCommand, env: Mapping[str, str] | None = None, *, timeout_secs: float
) -> subprocess.CompletedProcess[str]:
    """Run *command* verbatim through `sh -c` in its directory, in *env* (default: this process's environment).

    An OrchestratorCommand runs with DF_VERIFY_ROLE set to its role over whatever
    *env* holds, as dark-factory's verify (verify.py::_resolve_verify_env) and
    offline lane (offline_lane_runs.py::_lane_env) set it. The command runs in a
    session of its own, which no signal sent to this process reaches. If it is
    still running after *timeout_secs*, it is killed with every process in its
    session and CommandTimedOut is raised; if the call ends any other way before
    the command does, an interrupt or an error, they are killed too. A process
    that left the session, as a daemonizing tool's does, is beyond that kill, and
    the output it holds open is read for at most _DRAIN_AFTER_KILL_SECS more.
    """
    command_env = dict(os.environ if env is None else env)
    if isinstance(command, OrchestratorCommand):
        command_env["DF_VERIFY_ROLE"] = command.role
    shell = subprocess.Popen(
        command.command,
        shell=True,
        cwd=command.directory,
        env=command_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = shell.communicate(timeout=timeout_secs)
    except subprocess.TimeoutExpired:
        _kill_session(shell)
        stdout, stderr = _drain(shell)
        raise CommandTimedOut(command.command, command.directory, timeout_secs, stdout, stderr) from None
    finally:
        _kill_session(shell)
    return subprocess.CompletedProcess(command.command, shell.returncode, stdout, stderr)


def _drain(shell: subprocess.Popen[str]) -> tuple[str, str]:
    """Return what *shell*, whose session was just killed, printed to each stream.

    A stream ends once no process holds it, so a process that left the session
    can hold it open past the kill. The streams are read for at most
    _DRAIN_AFTER_KILL_SECS, then closed with what was read by then.
    """
    try:
        stdout, stderr = shell.communicate(timeout=_DRAIN_AFTER_KILL_SECS)
    except subprocess.TimeoutExpired as held_open:
        for stream in (shell.stdout, shell.stderr):
            if stream is not None:
                stream.close()
        shell.wait()
        return _decoded(held_open.stdout), _decoded(held_open.stderr)
    return stdout, stderr


def _decoded(output: bytes | None) -> str:
    """Return *output*, the bytes a timed-out read gathered, as text: Popen decodes only a read that finishes."""
    return (output or b"").decode(errors="replace")


def _kill_session(shell: subprocess.Popen[str]) -> None:
    """SIGKILL every process in *shell*'s session, unless Popen has already reaped *shell*.

    *shell* leads a session of its own, so its pid is the session's id, which cannot
    be reused until *shell* is reaped. The whole session is killed, not only
    *shell*'s process group, because a command can move processes into a group of
    their own inside it: GNU timeout, which several lane commands start with, calls
    setpgid, so killing only the shell's group would leave timeout, uv and pytest
    running.
    """
    if shell.returncode is not None:
        return
    for group in _process_groups_in_session(shell.pid):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(group, signal.SIGKILL)


def _process_groups_in_session(session: int) -> set[int]:
    """Return the process group of each process in the session *session*, found by listing /proc."""
    groups: set[int] = set()
    for pid in (int(entry) for entry in os.listdir("/proc") if entry.isdigit()):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if os.getsid(pid) == session:
                groups.add(os.getpgid(pid))
    return groups

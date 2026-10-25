# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one runner through which the orchestrator contract tests start a command, and the descriptions of how it ended.

run_command starts a command as the orchestrator does: verbatim through `sh -c`,
in the command's directory, and, for a command with a role, such as an
OrchestratorCommand, with DF_VERIFY_ROLE set to that role. The command runs in a
session of its own, and no process in that session outlives a hang: at its
timeout, every one of them is killed.

describe_outcome describes how any run ended: its exit code, then the tail of
each stream. describe_pytest_outcome describes a pytest run, such as the verify
suite's, with each ERRORS and FAILURES section of its report that stdout's tail
lacks ahead of those tails.

Usage::

    from tests._command_runner import (
        CommandTimedOut, ShellCommand, describe_outcome, describe_pytest_outcome, run_command,
    )
    from tests._orchestrator_config import verify_command

    result = run_command(verify_command(project_root, "test_command"), env, timeout_secs=600)
    assert result.returncode == 0, describe_pytest_outcome(result)
    version = run_command(ShellCommand("uv --version", project_root), timeout_secs=60)
    assert version.returncode == 0, describe_outcome(version)
"""

import contextlib
import os
import signal
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from tests._pytest_report import failure_sections

_STREAM_TAIL_CHARS = 5000

_FAILURE_SECTION_HEAD_CHARS = 20_000

_DRAIN_AFTER_KILL_SECS = 5

_MAX_KILL_SWEEPS = 10

VerifyRole = Literal["task", "offline"]


class Command(Protocol):
    """What run_command starts: the shell text, the directory it runs in, and the DF_VERIFY_ROLE it runs in, None for none of its own."""

    @property
    def command(self) -> str: ...

    @property
    def directory(self) -> Path: ...

    @property
    def role(self) -> VerifyRole | None: ...


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

    @property
    def role(self) -> None:
        return None


class Outcome(Protocol):
    """How a run ended: its exit code and what it printed to each stream."""

    @property
    def returncode(self) -> int: ...

    @property
    def stdout(self) -> str: ...

    @property
    def stderr(self) -> str: ...


def _tail(stream: str) -> str:
    """Return the end of *stream* that a description shows: its last _STREAM_TAIL_CHARS chars."""
    return stream[-_STREAM_TAIL_CHARS:]


def _tails(stdout: str, stderr: str) -> str:
    """Return the tail of each stream, so a long stderr, such as uv's log, cannot crowd out the end of stdout."""
    return f"stdout tail:\n{_tail(stdout)}\nstderr tail:\n{_tail(stderr)}"


def describe_outcome(outcome: Outcome) -> str:
    """Describe how *outcome*'s run ended, for an assertion message: its exit code, then the tail of each stream."""
    return f"exit {outcome.returncode}\n{_tails(outcome.stdout, outcome.stderr)}"


def describe_pytest_outcome(outcome: Outcome) -> str:
    """Describe how *outcome*'s pytest run ended, as describe_outcome does, with the failure sections stdout's tail lacks first.

    Those are the ERRORS and FAILURES sections of the pytest report in its stdout,
    which hold each failing test's traceback and captured output. pytest prints
    them before its warnings summary, so a long summary pushes them out of
    stdout's tail. Each keeps at most its first _FAILURE_SECTION_HEAD_CHARS chars.
    A stdout with neither, as when uv refused to start pytest or the run passed,
    or whose tail holds each whole, is described exactly as describe_outcome
    describes it.
    """
    stdout_tail = _tail(outcome.stdout)
    excerpts = "".join(
        _excerpt(section) for section in failure_sections(outcome.stdout) if section not in stdout_tail
    )
    return f"exit {outcome.returncode}\n{excerpts}{_tails(outcome.stdout, outcome.stderr)}"


def _excerpt(section: str) -> str:
    """Return *section* as a description quotes it, ending a line, so whatever follows starts a line of its own.

    A section longer than _FAILURE_SECTION_HEAD_CHARS keeps only that many of its
    first chars, then a line saying it was cut there and how long it was. So a
    section that holds hundreds of failures can neither crowd out the section
    after it nor put megabytes into a lane's log.
    """
    if len(section) > _FAILURE_SECTION_HEAD_CHARS:
        return (
            f"{section[:_FAILURE_SECTION_HEAD_CHARS]}\n"
            f"... this section is cut here, after the first {_FAILURE_SECTION_HEAD_CHARS} of its {len(section)} chars\n"
        )
    return section if section.endswith("\n") else f"{section}\n"


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
    command: Command, env: Mapping[str, str] | None = None, *, timeout_secs: float
) -> subprocess.CompletedProcess[str]:
    """Run *command* verbatim through `sh -c` in its directory, in *env* (default: this process's environment).

    A command with a role, such as an OrchestratorCommand, runs with DF_VERIFY_ROLE
    set to that role over whatever *env* holds, as dark-factory's verify
    (verify.py::_resolve_verify_env) and offline lane
    (offline_lane_runs.py::_lane_env) set it; a command without one, such as a
    ShellCommand, runs in whatever role *env* holds. The command runs in a session
    of its own, which no signal sent to this process reaches. If it is still
    running after *timeout_secs*, it is killed with every process in its session
    and CommandTimedOut is raised; if the call ends any other way before the
    command does, an interrupt or an error, they are killed too. A process that
    left the session, as a daemonizing tool's does, is beyond that kill, and the
    output it holds open is read for at most _DRAIN_AFTER_KILL_SECS more.
    """
    command_env = dict(os.environ if env is None else env)
    if command.role is not None:
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
    running. *shell*'s own group, whose id is the session's, is killed first, so
    the shell can start no further group while the session's others are looked
    for. Then each sweep kills every group /proc lists in the session that is not
    yet killed, until a sweep finds none or _MAX_KILL_SWEEPS have run: a process in
    a group of its own, such as a timeout whose command starts another, can start a
    group while a sweep looks. A killed group's processes stay listed until they
    are reaped, so a sweep looks only for groups not yet killed. Where /proc cannot
    be listed, as on macOS, only *shell*'s own group is killed.
    """
    if shell.returncode is not None:
        return
    _kill_group(shell.pid)
    killed = {shell.pid}
    for _ in range(_MAX_KILL_SWEEPS):
        found = _process_groups_in_session(shell.pid) - killed
        if not found:
            return
        for group in found:
            _kill_group(group)
        killed |= found


def _kill_group(group: int) -> None:
    """SIGKILL every process in the process group *group*, unless the group is gone or this process may not signal it."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(group, signal.SIGKILL)


def _process_groups_in_session(session: int) -> set[int]:
    """Return the group of each process /proc lists in the session *session*; none where /proc cannot be listed."""
    groups: set[int] = set()
    for pid in _pids_in_proc():
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if os.getsid(pid) == session:
                groups.add(os.getpgid(pid))
    return groups


def _pids_in_proc() -> list[int]:
    """Return the pid of each process /proc lists; none where /proc cannot be listed, as on macOS."""
    try:
        entries = os.listdir("/proc")
    except OSError:
        return []
    return [int(entry) for entry in entries if entry.isdigit()]

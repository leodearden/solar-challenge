# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_command_runner.py, the one runner through which the orchestrator contract tests start a command.

Each test runs a throwaway command, plain sh, with no uv and no mocks.
test_no_process_a_hung_probe_started_outlives_it covers every probe built on
run_command, not only run_command itself: collect, from tests/_collect_only.py,
and run_verify_suite, from tests/_verify_suite.py, are its cases, so this module
imports them, and their own test modules point here.
"""

import contextlib
import os
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from tests._collect_only import collect
from tests._command_runner import CommandTimedOut, ShellCommand, describe_outcome, run_command
from tests._orchestrator_config import OrchestratorCommand, lane_command, verify_command
from tests._verify_suite import run_verify_suite

_PROBE_VARIABLE = "COMMAND_RUNNER_PROBE"

_ECHO_ROLE = 'echo "${DF_VERIFY_ROLE-unset}"'

# Each hang outlasts the one before, so a shell that the host's load starts slowly still starts its background
# child before the kill.
_HANG_TIMEOUTS_SECS = (0.5, 2.0, 8.0)

# How a probe starts a hang command in a directory, with a timeout; it asserts the probe gave up on the hang.
ProbeStart = Callable[[str, Path, float], None]

_HOLDER_LIFETIME_SECS = 60

_HOLDER_SCRIPT = """\
import os
import pathlib
import sys
import time

pid_file, released_file, lifetime_secs = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), float(sys.argv[3])
os.setsid()
print("HELD-" + "OPEN", flush=True)
part = pid_file.with_name(pid_file.name + ".part")
part.write_text(str(os.getpid()))
part.rename(pid_file)
time.sleep(lifetime_secs)
released_file.touch()
"""


def _project_with_a_lane_job_and_a_test_command(project_root: Path, command: str) -> Path:
    """Make *project_root* a throwaway project whose lane job, named probe, and test_command each run *command*."""
    (project_root / "dark-factory-orchestrator.yaml").write_text(
        yaml.safe_dump(
            {"test_command": command, "git": {"offline_lane_commands": [{"name": "probe", "command": command}]}}
        ),
        encoding="utf-8",
    )
    return project_root


def _hang(directory: Path, pid_file: Path) -> str:
    """Write a hang script into *directory* and return the command that runs it.

    The script starts a long-lived child in the background, writes the child's pid
    to *pid_file*, and hangs in a shorter sleep of its own. The child writes to
    /dev/null rather than to the probe's output, and the script never waits on it,
    so the hang ends while the child still runs, even when the kill misses the child.
    """
    part, whole = shlex.quote(f"{pid_file}.part"), shlex.quote(str(pid_file))
    script = directory / "hang.sh"
    # The rename makes the pid file appear whole or not at all, wherever the kill interrupts the script.
    script.write_text(f"sleep 120 >/dev/null 2>&1 &\necho $! > {part} && mv {part} {whole}\nsleep 30\n", encoding="utf-8")
    return f"sh {shlex.quote(str(script))}"


def _hang_in_run_command(hang: str, directory: Path, timeout_secs: float) -> None:
    with pytest.raises(CommandTimedOut):
        run_command(ShellCommand(hang, directory), timeout_secs=timeout_secs)


def _hang_in_run_command_under_gnu_timeout(hang: str, directory: Path, timeout_secs: float) -> None:
    """GNU timeout puts itself and the hang in a process group of their own, inside the probe's session."""
    _hang_in_run_command(f"timeout 300 {hang}", directory, timeout_secs)


def _hang_in_collect(hang: str, directory: Path, timeout_secs: float) -> None:
    with pytest.raises(CommandTimedOut):
        collect(ShellCommand(hang, directory), timeout_secs=timeout_secs)


def _hang_in_run_verify_suite(hang: str, directory: Path, timeout_secs: float) -> None:
    """The hang is the test_command of a throwaway project in *directory*."""
    project_root = _project_with_a_lane_job_and_a_test_command(directory, hang)
    with pytest.raises(pytest.fail.Exception):
        run_verify_suite(project_root, os.environ, variant="in a probe", timeout_secs=timeout_secs)


def _pid_of_a_background_child_killed_in_a_hang(directory: Path, start: ProbeStart) -> int:
    """Hang a probe started by *start* in *directory* until the probe gives up on it; return its background child's pid."""
    pid_file = directory / "background.pid"
    hang = _hang(directory, pid_file)
    for timeout_secs in _HANG_TIMEOUTS_SECS:
        start(hang, directory, timeout_secs)
        if pid_file.exists():
            return int(pid_file.read_text(encoding="utf-8"))
    pytest.fail(f"the hang started no background child in hangs of {_HANG_TIMEOUTS_SECS} s")


def _holder_leaving_the_session(directory: Path, pid_file: Path, released_file: Path) -> str:
    """Write a holder script into *directory* and return the command that runs it.

    The holder leaves the probe's session, as a daemonizing tool's process does,
    so the kill of that session never reaches it. It prints a marker built as it
    runs, writes its pid to *pid_file*, holds the output it inherited open for
    _HOLDER_LIFETIME_SECS, and touches *released_file* as it lets go.
    """
    script = directory / "holder.py"
    script.write_text(_HOLDER_SCRIPT, encoding="utf-8")
    return shlex.join([sys.executable, str(script), str(pid_file), str(released_file), str(_HOLDER_LIFETIME_SECS)])


def _timed_out_once_the_holder_left_the_session(command: str, directory: Path, pid_file: Path) -> CommandTimedOut:
    """Run *command*, which starts a holder writing *pid_file*, until it times out after the holder left the session."""
    for timeout_secs in _HANG_TIMEOUTS_SECS:
        with pytest.raises(CommandTimedOut) as timed_out:
            run_command(ShellCommand(command, directory), timeout_secs=timeout_secs)
        if pid_file.exists():
            return timed_out.value
    pytest.fail(f"the holder never left the probe's session in hangs of {_HANG_TIMEOUTS_SECS} s")


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


def test_runs_the_command_verbatim_through_sh_in_its_directory_and_the_given_environment(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("in-the-command-directory\n", encoding="utf-8")
    command = f'cat marker.txt; echo "probe=${_PROBE_VARIABLE}"; echo on-stderr >&2; exit 3'

    result = run_command(ShellCommand(command, tmp_path), {**os.environ, _PROBE_VARIABLE: "given"}, timeout_secs=60)

    assert result.args == command
    assert result.returncode == 3, describe_outcome(result)
    assert result.stdout == "in-the-command-directory\nprobe=given\n", describe_outcome(result)
    assert result.stderr == "on-stderr\n", describe_outcome(result)


def test_given_no_environment_the_command_runs_in_this_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_PROBE_VARIABLE, "inherited")

    result = run_command(ShellCommand(f'echo "probe=${_PROBE_VARIABLE}"', tmp_path), timeout_secs=60)

    assert result.stdout == "probe=inherited\n", describe_outcome(result)


@pytest.mark.parametrize(
    ("command_of", "role"),
    [
        pytest.param(lambda project_root: lane_command(project_root, "probe"), "offline", id="lane-job"),
        pytest.param(lambda project_root: verify_command(project_root, "test_command"), "task", id="verify-slot"),
    ],
)
def test_an_orchestrator_command_runs_in_the_role_dark_factory_sets_for_it_over_an_inherited_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command_of: Callable[[Path], OrchestratorCommand], role: str
) -> None:
    """As dark-factory stamps DF_VERIFY_ROLE over whatever environment the command would otherwise inherit."""
    monkeypatch.setenv("DF_VERIFY_ROLE", "merge")
    project_root = _project_with_a_lane_job_and_a_test_command(tmp_path, _ECHO_ROLE)

    result = run_command(command_of(project_root), timeout_secs=60)

    assert result.stdout == f"{role}\n", describe_outcome(result)


@pytest.mark.parametrize(
    ("given", "printed"),
    [
        pytest.param({"DF_VERIFY_ROLE": "merge"}, "merge", id="role-given"),
        pytest.param({}, "unset", id="no-role-given"),
    ],
)
def test_a_shell_command_runs_in_the_given_environments_role_and_gets_none_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, given: dict[str, str], printed: str
) -> None:
    monkeypatch.delenv("DF_VERIFY_ROLE", raising=False)

    result = run_command(ShellCommand(_ECHO_ROLE, tmp_path), {**os.environ, **given}, timeout_secs=60)

    assert result.stdout == f"{printed}\n", describe_outcome(result)


def test_a_shell_command_whose_directory_is_not_a_directory_fails_naming_it_and_the_directory(tmp_path: Path) -> None:
    """As an OrchestratorCommand does, so no command reaches Popen's FileNotFoundError, which names neither."""
    absent = tmp_path / "absent"

    with pytest.raises(AssertionError) as failure:
        ShellCommand("true", absent)

    assert repr("true") in str(failure.value)
    assert str(absent) in str(failure.value)


def test_a_command_still_running_at_its_timeout_fails_naming_it_its_directory_its_timeout_and_its_output_so_far(
    tmp_path: Path,
) -> None:
    """printf builds each marker as the command runs, so only its output, never the command the message quotes, can put one in the message."""
    command = "printf OUT-%s SO-FAR; printf ERR-%s SO-FAR >&2; sleep 30"

    with pytest.raises(CommandTimedOut) as timed_out:
        run_command(ShellCommand(command, tmp_path), timeout_secs=1)

    message = str(timed_out.value)
    assert command in message
    assert str(tmp_path) in message
    assert "1 s" in message
    assert "OUT-SO-FAR" in message
    assert "ERR-SO-FAR" in message


@pytest.mark.parametrize(
    "start",
    [
        pytest.param(_hang_in_run_command, id="run_command"),
        pytest.param(_hang_in_run_command_under_gnu_timeout, id="run_command-under-gnu-timeout"),
        pytest.param(_hang_in_collect, id="collect"),
        pytest.param(_hang_in_run_verify_suite, id="run_verify_suite"),
    ],
)
def test_no_process_a_hung_probe_started_outlives_it(tmp_path: Path, start: ProbeStart) -> None:
    background_pid = _pid_of_a_background_child_killed_in_a_hang(tmp_path, start)

    outlived = not _gone_within(background_pid, seconds=10)
    if outlived:
        os.kill(background_pid, signal.SIGKILL)

    assert not outlived, (
        f"process {background_pid}, which the hung command started in the background, outlived the probe that "
        "gave up on it, so a hung probe would leave its processes running after the test that started it ends"
    )


def test_a_process_that_left_the_session_cannot_keep_a_timed_out_command_running_by_holding_its_output(
    tmp_path: Path,
) -> None:
    """The kill never reaches that process, so the runner stops reading after a bound and fails with what it read."""
    pid_file, released_file = tmp_path / "holder.pid", tmp_path / "holder.released"
    holder = _holder_leaving_the_session(tmp_path, pid_file, released_file)

    timed_out = _timed_out_once_the_holder_left_the_session(f"{holder} & sleep 30", tmp_path, pid_file)

    held_open = not released_file.exists()
    with contextlib.suppress(ProcessLookupError):
        os.kill(int(pid_file.read_text(encoding="utf-8")), signal.SIGKILL)
    assert held_open, (
        "the runner gave up on the timed-out command only once a process that had left its session let go of "
        "its output, so such a process keeps a probe running for as long as it runs"
    )
    assert "HELD-OPEN" in str(timed_out)


def test_an_outcome_is_described_by_its_exit_code_then_each_streams_own_tail() -> None:
    """A long stream keeps its end and loses its start, so neither stream can crowd the other's end out."""
    outcome = subprocess.CompletedProcess(
        "a command", 3, "STDOUT-HEAD" + "x" * 100_000 + "STDOUT-END", "STDERR-HEAD" + "y" * 100_000 + "STDERR-END"
    )

    description = describe_outcome(outcome)

    assert description.startswith("exit 3\n"), description[:200]
    assert "STDOUT-END" in description
    assert "STDERR-END" in description
    assert "STDOUT-HEAD" not in description
    assert "STDERR-HEAD" not in description


def test_an_outcome_whose_streams_are_short_is_described_with_both_whole() -> None:
    outcome = subprocess.CompletedProcess("a command", 0, "a short stdout\n", "a short stderr\n")

    description = describe_outcome(outcome)

    assert description.startswith("exit 0\n"), description
    assert "a short stdout\n" in description
    assert "a short stderr\n" in description

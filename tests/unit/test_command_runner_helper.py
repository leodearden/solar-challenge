# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_command_runner.py, the one runner through which the orchestrator contract tests start a command.

Each test runs a throwaway command, plain sh or pytest on a throwaway probe module, with no uv and no mocks.
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
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from tests._collect_only import collect
from tests._command_runner import (
    CommandTimedOut,
    ShellCommand,
    VerifyRole,
    describe_outcome,
    describe_pytest_outcome,
    run_command,
)
from tests._orchestrator_config import OrchestratorCommand, lane_command, verify_command
from tests._verify_suite import run_verify_suite

_PROBE_VARIABLE = "COMMAND_RUNNER_PROBE"

_ECHO_ROLE = 'echo "${DF_VERIFY_ROLE-unset}"'

# Each hang outlasts the one before, so a shell that the host's load starts slowly still starts its background
# child before the kill.
_HANG_TIMEOUTS_SECS = (0.5, 2.0, 8.0)

_REGROUP_TRIALS = 10

_REGROUP_TIMEOUT_SECS = 0.5

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

_PYTEST_PROBE_MODULE = """\
import warnings

import pytest


@pytest.fixture
def broken_at_setup() -> None:
    raise RuntimeError("SETUP-" + "MARKER")


def test_errors_at_setup(broken_at_setup: None) -> None:
    pass


def test_fails_after_printing() -> None:
    print("CAPTURED-" + "OUTPUT")
    assert False, "TRACEBACK-" + "MARKER"


def test_warns_two_hundred_times() -> None:
    for index in range(200):
        warnings.warn(f"WARNING-{index:03d} " + "w" * 100, UserWarning)
"""


@dataclass(frozen=True)
class _CommandOfAnotherType:
    """A command value that is neither a ShellCommand nor an OrchestratorCommand."""

    command: str
    directory: Path
    role: VerifyRole | None


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


def _regrouping_hang(directory: Path, pids_file: Path) -> str:
    """Write a regrouping hang script into *directory* and return the command that runs it.

    Until it is killed, the script starts a GNU timeout in the background every few
    milliseconds and appends its pid to *pids_file* in one write, so every line is
    whole. Each timeout moves itself and its sleep into a process group of their own
    inside the probe's session, as a lane command's timeout does. They write to
    /dev/null rather than to the probe's output, as _hang's child does, so a timeout
    the kill misses shows up as a survivor, not as a drain of the probe's output.
    """
    pids = shlex.quote(str(pids_file))
    script = directory / "regroup.sh"
    script.write_text(
        f"while :; do timeout 120 sleep 120 >/dev/null 2>&1 & echo $! >> {pids}; sleep 0.005; done\n", encoding="utf-8"
    )
    return f"sh {shlex.quote(str(script))}"


def _timeouts_a_regrouping_hang_started(directory: Path, start: ProbeStart) -> list[int]:
    """Hang *start*'s probe on a regrouping hang in a new *directory* until it gives up; return each timeout's pid."""
    directory.mkdir()
    pids_file = directory / "timeouts.pids"
    start(_regrouping_hang(directory, pids_file), directory, _REGROUP_TIMEOUT_SECS)
    if not pids_file.exists():
        return []
    return [int(line) for line in pids_file.read_text(encoding="utf-8").splitlines()]


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


def _not_gone_within(pids: Iterable[int], seconds: float) -> list[int]:
    """Return those of *pids* whose process is not gone, ended and reaped, within *seconds* of this call."""
    deadline = time.monotonic() + seconds
    existing = [pid for pid in pids if _process_exists(pid)]
    while existing and time.monotonic() < deadline:
        time.sleep(0.01)
        existing = [pid for pid in existing if _process_exists(pid)]
    return existing


def _run_failing_pytest(directory: Path) -> subprocess.CompletedProcess[str]:
    """Run pytest on _PYTEST_PROBE_MODULE, written to test_probe.py in *directory*, and return how it ended.

    Its report has an ERRORS section, a FAILURES section with captured output, and
    a warnings summary far longer than a stream's tail. Each marker the probe
    prints or raises is joined as it runs, so only pytest's report, never a source
    line it quotes, holds one whole. A pytest.ini of its own makes *directory* its
    rootdir, so this project's addopts and filterwarnings stay out of it, and
    PYTEST_ADDOPTS, which the newest-releases lane sets for the suite this test
    runs in, is dropped. -rN drops the short test summary, which pytest fills with
    a failure's message whenever its node id leaves room, so a marker can reach a
    description only through the report's sections, as the verify suite's long
    node ids force.
    """
    (directory / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (directory / "test_probe.py").write_text(_PYTEST_PROBE_MODULE, encoding="utf-8")
    command = shlex.join(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--color=no", "--tb=short", "-rN", "test_probe.py"]
    )
    env = {name: value for name, value in os.environ.items() if name != "PYTEST_ADDOPTS"}
    return run_command(ShellCommand(command, directory), env, timeout_secs=120)


def _report_separator(title: str) -> str:
    """Return the line with which pytest's report opens its section *title*: '=' runs either side of it."""
    fill = "=" * 30
    return f"{fill} {title} {fill}\n"


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


@pytest.mark.parametrize(
    ("role", "printed"),
    [
        pytest.param("task", "task", id="task"),
        pytest.param("offline", "offline", id="offline"),
        pytest.param(None, "merge", id="no-role"),
    ],
)
def test_a_command_of_any_type_runs_in_the_role_it_carries_and_with_none_in_the_inherited_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: VerifyRole | None, printed: str
) -> None:
    """Whether and how run_command sets DF_VERIFY_ROLE is the command's role field, never which type the command is."""
    monkeypatch.setenv("DF_VERIFY_ROLE", "merge")

    result = run_command(_CommandOfAnotherType(_ECHO_ROLE, tmp_path, role), timeout_secs=60)

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

    outlived = _not_gone_within([background_pid], seconds=10)
    if outlived:
        os.kill(background_pid, signal.SIGKILL)

    assert not outlived, (
        f"process {background_pid}, which the hung command started in the background, outlived the probe that "
        "gave up on it, so a hung probe would leave its processes running after the test that started it ends"
    )


@pytest.mark.parametrize(
    "start",
    [
        pytest.param(_hang_in_run_command, id="run_command"),
        pytest.param(_hang_in_run_command_under_gnu_timeout, id="run_command-under-gnu-timeout"),
    ],
)
def test_no_process_outlives_a_hung_command_that_keeps_moving_processes_into_groups_of_their_own(
    tmp_path: Path, start: ProbeStart
) -> None:
    """GNU timeout moves into a group of its own just after it starts, so one that the shell, or a process already in a group of its own, starts while the kill looks for the session's groups must not escape it."""
    started = 0
    for trial in range(_REGROUP_TRIALS):
        timeouts = _timeouts_a_regrouping_hang_started(tmp_path / f"trial-{trial}", start)
        survivors = _not_gone_within(timeouts, seconds=10)
        for survivor in survivors:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(survivor, signal.SIGKILL)
        assert not survivors, (
            f"in trial {trial}, the GNU timeouts {survivors}, which the hung command started, outlived the probe "
            "that gave up on it: a timeout that moved into a group of its own while the probe looked for the "
            "session's groups escaped the kill, so a lane command's timeout, or a timeout started under it, could "
            "leave its processes running"
        )
        started += len(timeouts)
    if not started:
        pytest.fail(
            f"the hang started no timeout in {_REGROUP_TRIALS} trials of {_REGROUP_TIMEOUT_SECS} s, so the test "
            "proved nothing"
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


def test_a_pytest_outcome_carries_its_reports_errors_and_failures_ahead_of_a_tail_its_warnings_summary_fills(
    tmp_path: Path,
) -> None:
    """pytest prints its ERRORS and FAILURES sections before its warnings summary, so a long summary fills the tail."""
    result = _run_failing_pytest(tmp_path)
    assert result.returncode == pytest.ExitCode.TESTS_FAILED, describe_outcome(result)
    assert "TRACEBACK-MARKER" not in describe_outcome(result), (
        "the probe's warnings summary no longer fills the tail of its stdout, so even describe_outcome keeps the "
        "probe's traceback and this test proves nothing"
    )

    description = describe_pytest_outcome(result)

    assert description.startswith("exit 1\n"), description[:200]
    assert "SETUP-MARKER" in description, description
    assert "TRACEBACK-MARKER" in description, description
    assert "CAPTURED-OUTPUT" in description, description
    assert description.index("TRACEBACK-MARKER") < description.index("WARNING-199 "), (
        f"the failure sections do not come ahead of the tail of stdout:\n{description}"
    )
    assert "WARNING-000 " not in description, (
        "the description holds the head of the warnings summary, which lies in neither a failure section nor the "
        "tail of stdout, so a failure section ran on past the next section's header"
    )


@pytest.mark.parametrize(
    "stdout",
    [
        pytest.param("", id="uv-refused-before-pytest"),
        pytest.param(
            _report_separator("test session starts")
            + "test_probe.py::test_passes PASSED [100%]\n"
            + _report_separator("1 passed in 0.01s"),
            id="green-report",
        ),
    ],
)
def test_a_pytest_outcome_with_no_failure_section_is_described_as_any_outcome(stdout: str) -> None:
    """With no ERRORS or FAILURES section in stdout, there is nothing to put ahead of the tails."""
    outcome = subprocess.CompletedProcess(
        "a command", 2, stdout, "error: The lockfile at `uv.lock` needs to be updated\n"
    )

    assert describe_pytest_outcome(outcome) == describe_outcome(outcome)


def test_a_pytest_outcome_keeps_the_head_of_each_long_failure_section_and_says_how_long_it_was() -> None:
    """Each section has its own bound, so a long ERRORS section cannot crowd FAILURES out, as each stream keeps its own tail."""
    errors_section = _report_separator("ERRORS") + "ERRORS-HEAD" + "x" * 1_000_000 + "ERRORS-END\n"
    stdout = (
        _report_separator("test session starts")
        + errors_section
        + _report_separator("FAILURES")
        + "FAILURES-MARKER\n"
        + _report_separator("warnings summary")
        + "a warning\n" * 10_000
        + _report_separator("1 failed, 1 error in 0.01s")
    )
    outcome = subprocess.CompletedProcess("a command", 1, stdout, "")

    description = describe_pytest_outcome(outcome)

    assert "ERRORS-HEAD" in description
    assert "ERRORS-END" not in description
    assert str(len(errors_section)) in description
    assert "FAILURES-MARKER" in description


def test_a_pytest_outcome_quotes_no_failure_section_that_its_stdout_tail_already_holds() -> None:
    """Quoting such a section ahead of the tails too would print each of its failures twice."""
    errors_section = _report_separator("ERRORS") + "ERRORS-MARKER\n" + "x" * 10_000 + "\n"
    stdout = (
        _report_separator("test session starts")
        + errors_section
        + _report_separator("FAILURES")
        + "FAILURES-MARKER\n"
        + _report_separator("1 failed, 1 error in 0.01s")
    )
    outcome = subprocess.CompletedProcess("a command", 1, stdout, "")

    description = describe_pytest_outcome(outcome)

    assert description.count("ERRORS-MARKER") == 1, description
    assert description.count("FAILURES-MARKER") == 1, description

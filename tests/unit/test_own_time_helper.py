# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_own_time.py, which bounds a real child's process group by its own time.

A group's own time is the wall-clock time of a wait less the time its members spent queued
for a CPU. Time a member spends blocked counts, so a hung group still fails its budget; time
the host keeps it runnable but off a CPU does not, so a crowded host fails a wait only at its
wall-clock limit. The wait's rules run on a scripted host, so no verdict here depends on how
busy the real one is; real processes check only what the real host provides, and what a
run of a command gives back.
"""

import contextlib
import math
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests._own_time import (
    LINUX_HOST,
    WALL_LIMIT_IN_BUDGETS,
    MemberSnapshot,
    OwnTimeExceeded,
    Reading,
    WallLimitExceeded,
    run_on_own_time,
    wait_on_own_time,
)

_on_linux = pytest.mark.skipif(sys.platform != "linux", reason="LINUX_HOST reads /proc/PID/stat and /proc/PID/schedstat")

_ANY_GROUP = 1
_LEADER = 1
_GRANDCHILD = 3

_SCRIPTED_TIME_CEILING_SECS = 1000.0

# How long a real process may take to reach a state the test waits for, on a host however busy.
_SETTLES_WITHIN_SECS = 60.0

_REAL_PROCESS_LIFETIME_SECS = 30

# A budget of own time no short command's start-up spends, however busy the host, since time queued for a CPU is
# not its own.
_SHORT_COMMAND_BUDGET_SECS = 30.0

_HANG_BUDGET_SECS = 2.0

# How long a killed member may take to be gone, ended and reaped.
_GONE_WITHIN_SECS = 10.0

_ONE_MIB = 1024 * 1024


@dataclass(frozen=True)
class _ScriptedMember:
    """A member of a scripted group, present from fake time *born* until *gone*.

    It spends *on_cpu_share* of its life on a CPU and is credited *run_delay_share*
    of it as run delay, in *state* throughout. Its times move until *progress_until*
    and then stay still.
    """

    on_cpu_share: float = 0.0
    run_delay_share: float = 0.0
    state: str = "S"
    born: float = 0.0
    gone: float = math.inf
    progress_until: float = math.inf

    def at(self, now: float) -> MemberSnapshot | None:
        """The member's snapshot at fake time *now*, or None while it is not in the group."""
        if not self.born <= now < self.gone:
            return None
        lived = min(now, self.progress_until) - self.born
        return MemberSnapshot(on_cpu=self.on_cpu_share * lived, run_delay=self.run_delay_share * lived, state=self.state)


@dataclass
class _ScriptedHost:
    """A scripted host, structurally a tests._own_time.GroupHost, whichever group it is asked about.

    Fake time starts at *now* and moves only when the wait sleeps; each sleep is kept
    in *sleeps*. The group holds each of *scripted*'s members present at that time.
    """

    scripted: Mapping[int, _ScriptedMember]
    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def wall(self) -> float:
        return self.now

    def members(self, group: int) -> dict[int, MemberSnapshot]:
        return {pid: snapshot for pid, member in self.scripted.items() if (snapshot := member.at(self.now)) is not None}

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if self.now > _SCRIPTED_TIME_CEILING_SECS:
            pytest.fail(f"the wait outlasted {_SCRIPTED_TIME_CEILING_SECS:g} s of scripted time")

    @property
    def poll(self) -> float:
        """The longest the wait slept between two readings."""
        return max(self.sleeps)


def _wait(host: _ScriptedHost, done: Callable[[], bool], *, budget_secs: float) -> None:
    wait_on_own_time(_ANY_GROUP, done, budget_secs=budget_secs, host=host)


def test_run_delay_credited_to_a_member_that_is_not_runnable_does_not_count() -> None:
    """The member is on a CPU for an eighth of the wait and credited the rest as run
    delay, so its condition comes true 2.4 s in, after 0.3 s of its own time: the wait
    outlasts its 1 s budget and returns rather than fails."""
    host = _ScriptedHost({_LEADER: _ScriptedMember(on_cpu_share=1 / 8, run_delay_share=7 / 8)})

    _wait(host, lambda: host.now >= 2.4, budget_secs=1.0)


def test_time_a_member_spends_blocked_counts() -> None:
    """A blocked member whose times stay still is queued for no CPU, so all the wait is its own time."""
    budget_secs = 1.0
    host = _ScriptedHost({_LEADER: _ScriptedMember()})

    with pytest.raises(OwnTimeExceeded) as raised:
        _wait(host, lambda: False, budget_secs=budget_secs)

    assert raised.value.budget_secs == budget_secs
    assert budget_secs < raised.value.reading.elapsed <= budget_secs + host.poll


def test_run_delay_credited_to_a_member_that_has_left_the_group_still_counts_as_queued() -> None:
    """The grandchild is credited all its time as run delay and leaves the group 8 s in,
    while the leader sleeps throughout, waiting on it. The grandchild's run delay covers
    the leader's wait until then, so only about a budget of the leader's blocked time
    after the grandchild left fails the wait."""
    left_at, budget_secs = 8.0, 1.0
    host = _ScriptedHost({_LEADER: _ScriptedMember(), _GRANDCHILD: _ScriptedMember(run_delay_share=1, gone=left_at)})

    with pytest.raises(OwnTimeExceeded) as raised:
        _wait(host, lambda: False, budget_secs=budget_secs)

    assert left_at + budget_secs - host.poll < raised.value.reading.elapsed <= left_at + budget_secs + host.poll


def test_a_member_first_seen_after_the_wait_began_has_all_its_run_delay_counted() -> None:
    """The grandchild is born between two readings and credited all its life as run
    delay, so the run delay it had when first seen counts as well."""
    born = 0.01
    host = _ScriptedHost({_LEADER: _ScriptedMember(), _GRANDCHILD: _ScriptedMember(run_delay_share=1, born=born)})

    with pytest.raises(WallLimitExceeded) as raised:
        _wait(host, lambda: False, budget_secs=1.0)

    reading = raised.value.reading
    assert reading.run_delay == pytest.approx(reading.elapsed - born)


def test_run_delay_credited_before_the_wait_began_does_not_count() -> None:
    """The member had been credited its first 100 s as run delay when the wait began,
    and is blocked since, so the wait fails at its budget and reports only what the
    group spent since it began."""
    budget_secs = 1.0
    host = _ScriptedHost({_LEADER: _ScriptedMember(run_delay_share=1, progress_until=100.0)}, now=100.0)

    with pytest.raises(OwnTimeExceeded) as raised:
        _wait(host, lambda: False, budget_secs=budget_secs)

    reading = raised.value.reading
    assert budget_secs < reading.elapsed <= budget_secs + host.poll
    assert (reading.on_cpu, reading.run_delay) == (0.0, 0.0)


def test_a_queue_stint_the_kernel_has_not_credited_does_not_count() -> None:
    """The member is runnable and its times never move, which is one queue stint the
    kernel credits only once it ends. The condition comes true 3.5 s in, past the 1 s
    budget, so the wait returns rather than fails."""
    host = _ScriptedHost({_LEADER: _ScriptedMember(state="R")})

    _wait(host, lambda: host.now >= 3.5, budget_secs=1.0)


@pytest.mark.parametrize("state", ["S", "R"])
def test_a_group_credited_all_the_wait_as_queued_fails_at_the_wall_limit(state: str) -> None:
    """A group with no own time, seen runnable or not, ends its wait only at the wall limit, WALL_LIMIT_IN_BUDGETS
    budgets long."""
    budget_secs = 1.0
    wall_limit_secs = WALL_LIMIT_IN_BUDGETS * budget_secs
    host = _ScriptedHost({_LEADER: _ScriptedMember(run_delay_share=1, state=state)})

    with pytest.raises(WallLimitExceeded) as raised:
        _wait(host, lambda: False, budget_secs=budget_secs)

    reading = raised.value.reading
    assert raised.value.budget_secs == budget_secs
    assert wall_limit_secs < reading.elapsed <= wall_limit_secs + host.poll
    assert reading.own <= budget_secs


@pytest.mark.parametrize(
    ("member", "limit_in_budgets"),
    [
        pytest.param(_ScriptedMember(), 1, id="own-time-budget"),
        pytest.param(_ScriptedMember(run_delay_share=1), WALL_LIMIT_IN_BUDGETS, id="wall-limit"),
    ],
)
def test_a_condition_that_holds_at_the_reading_past_a_limit_ends_the_wait(
    member: _ScriptedMember, limit_in_budgets: int
) -> None:
    """The condition comes true at the first reading past the limit, so the wait returns rather than fails."""
    budget_secs = 1.0
    host = _ScriptedHost({_LEADER: member})

    _wait(host, lambda: host.now > limit_in_budgets * budget_secs, budget_secs=budget_secs)


def test_a_reading_reports_every_figure_it_holds() -> None:
    """The figures differ, so each shows in the report as itself and none can stand in for another."""
    reading = Reading(elapsed=9.0, on_cpu=1.0, run_delay=2.0, uncredited=3.0)
    figures = {
        "elapsed": reading.elapsed,
        "on_cpu": reading.on_cpu,
        "run_delay": reading.run_delay,
        "uncredited": reading.uncredited,
        "own": reading.own,
    }

    report = str(reading)

    assert [name for name, seconds in figures.items() if f"{seconds:.2f} s" not in report] == []


def test_a_reading_never_reports_a_negative_own_time() -> None:
    """The bound on an uncredited stint can overlap run delay already credited, but own time cannot go below 0."""
    reading = Reading(elapsed=1.5, on_cpu=0.0, run_delay=1.5, uncredited=0.25)

    assert reading.own == 0.0


def _members_once_asleep(group: int, pids: Callable[[], set[int]]) -> Mapping[int, MemberSnapshot]:
    """LINUX_HOST's members of *group* once each of *pids*, asked anew at every poll, is one in state S.

    Fail if they never are within _SETTLES_WITHIN_SECS, as a process the host keeps queued may take a while to sleep.
    """
    deadline = time.monotonic() + _SETTLES_WITHIN_SECS
    while True:
        members, expected = LINUX_HOST.members(group), pids()
        if expected and all(pid in members and members[pid].state == "S" for pid in expected):
            return members
        if time.monotonic() > deadline:
            pytest.fail(f"{sorted(expected)} were not all asleep in group {group} within {_SETTLES_WITHIN_SECS:g} s: {members}")
        time.sleep(0.05)


def _kill_and_reap(leader: subprocess.Popen[bytes]) -> None:
    """SIGKILL *leader*'s whole group and reap the leader."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(leader.pid, signal.SIGKILL)
    leader.wait()


@_on_linux
def test_the_host_reads_every_member_of_a_real_group(tmp_path: Path) -> None:
    """The group's leader, a shell, starts a background sleep, a grandchild of this process, and waits on it.

    The shell writes the sleep's pid to a .part file and renames it, so the pid file appears whole or not at all.
    """
    pid_file = tmp_path / "grandchild.pid"
    part, whole = shlex.quote(f"{pid_file}.part"), shlex.quote(str(pid_file))
    script = f"sleep {_REAL_PROCESS_LIFETIME_SECS} & echo $! > {part} && mv {part} {whole}; wait"
    leader = subprocess.Popen(["sh", "-c", script], process_group=0)
    try:
        members = _members_once_asleep(
            leader.pid, lambda: {leader.pid, int(pid_file.read_text())} if pid_file.exists() else set()
        )

        assert os.getpid() not in members
    finally:
        _kill_and_reap(leader)


@_on_linux
def test_the_host_reads_the_state_of_a_member_named_with_a_space_and_a_parenthesis(tmp_path: Path) -> None:
    """/proc/PID/stat gives the process's name, in parentheses, before its state, so the member's name holds ') '.

    The member exits at once and stays unreaped, so its state is Z.
    """
    sleep = shutil.which("sleep")
    assert sleep is not None, "no sleep on PATH"
    named = tmp_path / "a) b"
    shutil.copy(sleep, named)
    member = subprocess.Popen([str(named), "0"], process_group=0)
    try:
        os.waitid(os.P_PID, member.pid, os.WEXITED | os.WNOWAIT)

        assert {pid: snapshot.state for pid, snapshot in LINUX_HOST.members(member.pid).items()} == {member.pid: "Z"}
    finally:
        _kill_and_reap(member)


def _hang(directory: Path, pid_file: Path) -> list[str]:
    """Write a hang script into *directory* and return the command that runs it.

    The script prints a marker, starts a long-lived sleep in the background, writes
    that sleep's pid to *pid_file*, and hangs in a shorter sleep of its own, all
    blocked, so its time is its own. The rename makes the pid file appear whole or
    not at all.
    """
    part, whole = shlex.quote(f"{pid_file}.part"), shlex.quote(str(pid_file))
    script = directory / "hang.sh"
    script.write_text(
        f"echo hanging\nsleep 120 >/dev/null 2>&1 &\necho $! > {part} && mv {part} {whole}\nsleep 30\n", encoding="utf-8"
    )
    return ["sh", str(script)]


def _process_exists(pid: int) -> bool:
    """Whether a process *pid* exists, a zombie included."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone_within(pid: int, seconds: float) -> bool:
    """Whether the process *pid* is gone, ended and reaped, within *seconds* of this call."""
    deadline = time.monotonic() + seconds
    while _process_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    return not _process_exists(pid)


@_on_linux
def test_a_run_returns_the_commands_exit_status_and_everything_it_wrote(tmp_path: Path) -> None:
    args = ["sh", "-c", "echo out; echo err >&2; exit 3"]

    run = run_on_own_time(args, budget_secs=_SHORT_COMMAND_BUDGET_SECS, cwd=tmp_path)

    assert (run.args, run.returncode, run.stdout, run.stderr) == (args, 3, "out\n", "err\n")


@_on_linux
def test_a_run_is_given_its_env_and_cwd(tmp_path: Path) -> None:
    run = run_on_own_time(
        ["sh", "-c", 'pwd; echo "$OWN_TIME_PROBE"'],
        budget_secs=_SHORT_COMMAND_BUDGET_SECS,
        cwd=tmp_path,
        env={**os.environ, "OWN_TIME_PROBE": "x"},
    )

    assert run.stdout == f"{tmp_path.resolve()}\nx\n"


@_on_linux
def test_a_run_whose_group_outspends_its_budget_fails_naming_its_command_and_output_and_leaves_no_member_running(
    tmp_path: Path,
) -> None:
    """The hang's shell and both its sleeps are blocked, so the run fails about a budget in, its background sleep
    killed with the rest of its group."""
    pid_file = tmp_path / "background.pid"
    args = _hang(tmp_path, pid_file)

    with pytest.raises(OwnTimeExceeded) as raised:
        run_on_own_time(args, budget_secs=_HANG_BUDGET_SECS, cwd=tmp_path)

    notes = "\n".join(raised.value.__notes__)
    assert shlex.join(args) in notes and "hanging" in notes, notes
    assert pid_file.exists(), "the hang started no background sleep within its budget"
    background_pid = int(pid_file.read_text(encoding="utf-8"))
    assert _gone_within(background_pid, _GONE_WITHIN_SECS), (
        f"the hang's background sleep {background_pid} still runs {_GONE_WITHIN_SECS:g} s after its run failed"
    )


@_on_linux
def test_a_runs_output_is_not_lost_to_a_full_pipe(tmp_path: Path) -> None:
    """The command writes far more than a pipe holds before it exits, so a run that read a pipe only once the command
    had exited would leave it blocked, spending its own time, until the run failed."""
    args = [sys.executable, "-I", "-c", f"import sys; sys.stdout.write('o' * {_ONE_MIB})"]

    run = run_on_own_time(args, budget_secs=_SHORT_COMMAND_BUDGET_SECS, cwd=tmp_path)

    assert (run.returncode, run.stdout) == (0, "o" * _ONE_MIB)

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bound a real child's process group by its own time, with the wall clock only a backstop.

A group's own time is the wall-clock time since a wait began, less the time its
members spent queued for a CPU: the run delay Linux credits each one in
/proc/PID/schedstat, and a bound on any queue stint it has not credited yet. Time a
member spends running or blocked counts, so a hung command still fails its budget;
time the host keeps it runnable but off a CPU does not, so a crowded host fails a
wait only at its wall-clock limit, WALL_LIMIT_IN_BUDGETS budgets long. The whole
process group is metered because a command such as `npm run build:css` does its work
in grandchildren while each parent sleeps. It reads /proc, so it is Linux-only.

Use run_on_own_time in place of `subprocess.run(..., timeout=...)` for a real child.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Protocol

WALL_LIMIT_IN_BUDGETS = 20

# Each poll scans all of /proc, so polling more often would take CPU from the group it meters.
_POLL_INTERVAL_SECS = 0.25


@dataclass(frozen=True)
class MemberSnapshot:
    """One group member's times and state at one reading.

    *on_cpu* and *run_delay* are the seconds its main thread has spent on a CPU, and
    been credited as run delay, since it started; *state* is its proc(5) state letter.
    """

    on_cpu: float
    run_delay: float
    state: str

    @property
    def runnable(self) -> bool:
        """Whether the member is on a CPU or queued for one."""
        return self.state == "R"


_AT_BIRTH = MemberSnapshot(on_cpu=0.0, run_delay=0.0, state="R")


class GroupHost(Protocol):
    """What a wait reads and spends its time through: the host, or a scripted host."""

    def wall(self) -> float: ...

    def members(self, group: int) -> Mapping[int, MemberSnapshot]:
        """Each live process whose process group is *group*, by pid.

        Each one's state is read before its times, so the run delay in its times
        counts all the time a member seen not runnable had spent queued by that read.
        """
        ...

    def sleep(self, seconds: float) -> None: ...


class _LinuxHost:
    """The host's monotonic clock and sleep, and each group member's /proc files."""

    def wall(self) -> float:
        return time.monotonic()

    def members(self, group: int) -> dict[int, MemberSnapshot]:
        members: dict[int, MemberSnapshot] = {}
        for pid in _pids_in_group(group):
            with contextlib.suppress(FileNotFoundError, ProcessLookupError):
                members[pid] = _snapshot(pid)
        return members

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


LINUX_HOST = _LinuxHost()


def _pids_in_group(group: int) -> list[int]:
    """The pid of each process /proc lists in the process group *group*."""
    pids: list[int] = []
    for pid in (int(entry) for entry in os.listdir("/proc") if entry.isdigit()):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if os.getpgid(pid) == group:
                pids.append(pid)
    return pids


def _snapshot(pid: int) -> MemberSnapshot:
    """The process *pid*'s state, read first, then its times."""
    # The state follows the process's name, which is in parentheses and may itself hold spaces and ')'.
    state = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
    on_cpu_ns, run_delay_ns, _ = Path(f"/proc/{pid}/schedstat").read_text().split()
    return MemberSnapshot(on_cpu=int(on_cpu_ns) / 1e9, run_delay=int(run_delay_ns) / 1e9, state=state)


@dataclass(frozen=True)
class Reading:
    """How a wait's process group had spent the wait, at one poll.

    *elapsed* is how long the wait had lasted. *on_cpu* and *run_delay* are what
    every member seen during it spent on a CPU, and was credited as run delay, in
    that time, summed. *uncredited* bounds the time the members present at the poll
    may have spent queued for a CPU that their run delay does not count yet.
    """

    elapsed: float
    on_cpu: float
    run_delay: float
    uncredited: float

    @property
    def own(self) -> float:
        """The group's own time: the wait's, less *run_delay* and *uncredited*, never below 0."""
        return max(0.0, self.elapsed - self.run_delay - self.uncredited)

    def __str__(self) -> str:
        return (
            f"after {self.elapsed:.2f} s, the process group had spent {self.on_cpu:.2f} s on a CPU, been credited "
            f"{self.run_delay:.2f} s of run delay and may have been queued for a CPU {self.uncredited:.2f} s more, "
            f"leaving {self.own:.2f} s as its own"
        )


@dataclass(frozen=True)
class _MemberRecord:
    """What a wait knows of one member.

    *baseline* is its snapshot when the wait began to count it, *latest* its latest
    one, *read_at* how far into the wait that latest one was read, and *uncredited*
    the bound on its queue time not yet credited at that reading.
    """

    baseline: MemberSnapshot
    latest: MemberSnapshot
    read_at: float
    uncredited: float

    @property
    def on_cpu(self) -> float:
        return self.latest.on_cpu - self.baseline.on_cpu

    @property
    def run_delay(self) -> float:
        return self.latest.run_delay - self.baseline.run_delay

    def after(self, snapshot: MemberSnapshot, elapsed: float) -> _MemberRecord:
        """This record once the wait has read *snapshot* of its member, *elapsed* seconds in.

        A member that is not runnable is in no queue stint. A runnable one whose times
        have moved is in no stint that began before its previous reading; one whose
        times have not may still be in the stint it was in then.
        """
        since = elapsed - self.read_at
        progressed = (snapshot.on_cpu, snapshot.run_delay) != (self.latest.on_cpu, self.latest.run_delay)
        if not snapshot.runnable:
            uncredited = 0.0
        elif progressed:
            uncredited = since
        else:
            uncredited = self.uncredited + since
        return replace(self, latest=snapshot, read_at=elapsed, uncredited=uncredited)


@dataclass(frozen=True)
class _GroupMeter:
    """The readings of one wait: a record of every member it has seen, by pid, and its latest *reading*."""

    records: Mapping[int, _MemberRecord]
    reading: Reading

    @classmethod
    def starting_from(cls, members: Mapping[int, MemberSnapshot]) -> _GroupMeter:
        """The meter when the wait takes *members* as their baselines, before any time has passed."""
        records = {pid: _MemberRecord(snapshot, snapshot, read_at=0.0, uncredited=0.0) for pid, snapshot in members.items()}
        return cls(records, Reading(elapsed=0.0, on_cpu=0.0, run_delay=0.0, uncredited=0.0))

    def after_reading(self, members: Mapping[int, MemberSnapshot], *, elapsed: float) -> _GroupMeter:
        """This meter once the wait has read *members*, *elapsed* seconds in.

        A member absent from *members* keeps its record, so the run delay it was
        credited still counts, but it has no uncredited time.
        """
        present = {pid: self._record_of(pid).after(snapshot, elapsed) for pid, snapshot in members.items()}
        records = {**self.records, **present}
        reading = Reading(
            elapsed=elapsed,
            on_cpu=sum(record.on_cpu for record in records.values()),
            run_delay=sum(record.run_delay for record in records.values()),
            uncredited=sum(record.uncredited for record in present.values()),
        )
        return _GroupMeter(records, reading)

    def _record_of(self, pid: int) -> _MemberRecord:
        """The record of the member *pid*; for one not seen before, born since the wait's latest reading, a newborn's."""
        newborn = _MemberRecord(_AT_BIRTH, _AT_BIRTH, read_at=self.reading.elapsed, uncredited=0.0)
        return self.records.get(pid, newborn)


class OwnTimeExceeded(TimeoutError):
    """A wait whose process group spent more than its budget of its own time; the message leads with its *reading*."""

    def __init__(self, *, budget_secs: float, reading: Reading) -> None:
        super().__init__(f"{reading}, past its {budget_secs:g} s budget of own time")
        self.budget_secs = budget_secs
        self.reading = reading


class WallLimitExceeded(TimeoutError):
    """A wait that outlasted its wall-clock limit with its group's own time within budget, as on a host that keeps
    the group queued for a CPU; the message leads with its *reading*."""

    def __init__(self, *, budget_secs: float, reading: Reading) -> None:
        super().__init__(
            f"{reading}, past its {WALL_LIMIT_IN_BUDGETS * budget_secs:g} s wall-clock limit, "
            f"{WALL_LIMIT_IN_BUDGETS} budgets of {budget_secs:g} s"
        )
        self.budget_secs = budget_secs
        self.reading = reading


def wait_on_own_time(
    group: int, done: Callable[[], bool], *, budget_secs: float, host: GroupHost = LINUX_HOST
) -> None:
    """Poll the process group *group* until *done* holds, failing once the group has spent more than
    *budget_secs* of its own time on the wait, or once the wait has lasted WALL_LIMIT_IN_BUDGETS budgets.

    *done* is checked after each poll's reading and before that reading is held
    against either limit, so a condition that comes true while this process is itself
    starved of a CPU never fails the wait. The wait reads the group before it starts
    its clock, and the clock before the group at every poll, so a stall of this
    process can only understate the group's own time.

    Raises:
        OwnTimeExceeded: *done* was still false once the group's own time exceeded *budget_secs*.
        WallLimitExceeded: *done* was still false once the wait passed its wall-clock limit.
    """
    meter = _GroupMeter.starting_from(host.members(group))
    started = host.wall()
    while True:
        elapsed = host.wall() - started
        meter = meter.after_reading(host.members(group), elapsed=elapsed)
        if done():
            return
        _fail_past_a_limit(meter.reading, budget_secs)
        host.sleep(_POLL_INTERVAL_SECS)


def _fail_past_a_limit(reading: Reading, budget_secs: float) -> None:
    """Raise if *reading* is past the budget of own time or the wall-clock limit."""
    if reading.own > budget_secs:
        raise OwnTimeExceeded(budget_secs=budget_secs, reading=reading)
    if reading.elapsed > WALL_LIMIT_IN_BUDGETS * budget_secs:
        raise WallLimitExceeded(budget_secs=budget_secs, reading=reading)


def run_on_own_time(
    args: Sequence[str], *, budget_secs: float, cwd: Path, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the command *args* in *cwd*, with *env*, to its exit, waiting on its process group as wait_on_own_time does.

    Return what subprocess.run returns with capture_output=True, text=True and
    errors="backslashreplace". The command leads a process group of its own, not a
    session, so it stays in this process's autogroup, at the nice this process runs
    at. Its output goes to unnamed temporary files, not pipes, as a member blocked on
    a full pipe would be spending its own time. However the wait ends, every member
    of the group still running is killed before the command is reaped, so none
    outlives the run. A failed wait's exception is noted with the command, its
    directory and everything it wrote.

    Raises:
        OwnTimeExceeded: as wait_on_own_time raises it.
        WallLimitExceeded: as wait_on_own_time raises it.
    """
    command = list(args)
    with (
        tempfile.TemporaryFile("w+", errors="backslashreplace") as stdout,
        tempfile.TemporaryFile("w+", errors="backslashreplace") as stderr,
    ):
        leader = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr, process_group=0)
        try:
            _wait_then_end_group(leader, budget_secs)
        except (OwnTimeExceeded, WallLimitExceeded) as exceeded:
            exceeded.add_note(
                f"running {shlex.join(command)} in {cwd}\n"
                f"its stdout:\n{_written_to(stdout)}\n"
                f"its stderr:\n{_written_to(stderr)}"
            )
            raise
        return subprocess.CompletedProcess(command, leader.returncode, _written_to(stdout), _written_to(stderr))


def _wait_then_end_group(leader: subprocess.Popen[bytes], budget_secs: float) -> None:
    """Wait on *leader*'s process group until *leader* exits; then, however the wait ended, kill the group and reap
    *leader*.

    *leader* stays unreaped until its group is killed, so its /proc files stay
    readable to the wait and no other group can take its group's id.
    """
    try:
        wait_on_own_time(leader.pid, lambda: _exited_unreaped(leader.pid), budget_secs=budget_secs)
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(leader.pid, signal.SIGKILL)
        leader.wait()


def _exited_unreaped(pid: int) -> bool:
    """Whether this process's child *pid* has exited, observed without reaping it."""
    return os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None


def _written_to(file: IO[str]) -> str:
    """Everything written to *file* so far."""
    file.seek(0)
    return file.read()

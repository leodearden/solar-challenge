# SPDX-License-Identifier: AGPL-3.0-or-later
"""Home simulators for FleetRunner tests: one marks each home as it starts and as it finishes, so a test reads back which homes started, in which process, on which weather, and which finished; one ends its worker process at named homes, to break a pool.

A FleetRunner's pool pickles its home simulator into each job, so a spawn or forkserver
worker imports this module to unpickle it. That is why each simulator is a top-level class
of a helper module rather than one defined in a test.

Usage::

    from tests._fleet_runner import (
        MarkingHomeSimulator, ProcessEndingHomeSimulator, finished, started, wait_until_started
    )

    runner = FleetRunner(weather=weather, home_simulator=MarkingHomeSimulator(tmp_path, failing=frozenset({"Home 1"})))
    with pytest.raises(ValueError, match="Home 1 cannot be simulated"):
        runner.simulate(fleet, start, end)
    assert len(started(tmp_path)) < len(fleet.homes)
    assert finished(tmp_path) == set(started(tmp_path))

    marking = FleetRunner(weather=weather, home_simulator=MarkingHomeSimulator(tmp_path, seconds=0.2))
    each = marking.simulate_each(fleets, start, end)
    next(each)
    wait_until_started(tmp_path, 2, within=10)
    each.close()
    assert finished(tmp_path) == set(started(tmp_path))

    breaking = ProcessEndingHomeSimulator(MarkingHomeSimulator(tmp_path), ending=frozenset({"Home 2"}))
    with pytest.raises(BrokenProcessPool):
        FleetRunner(weather=weather, home_simulator=breaking, parallel=True).simulate(fleet, start, end)
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.weather import PrefetchedWeather, WeatherProvider
from tests._finance_builders import make_sim_results

_STARTED_SUFFIX = ".json"
_FINISHED_SUFFIX = ".finished"


@dataclass(frozen=True)
class HomeStart:
    """What MarkingHomeSimulator recorded as a home started: the id of the process it ran in, and the names of the locations its weather held, None for weather other than a PrefetchedWeather."""

    pid: int
    locations: tuple[str, ...] | None


@dataclass(frozen=True)
class MarkingHomeSimulator:
    """A HomeSimulator that marks each home it starts in *marker_dir*, waits *seconds*, refuses each home named in *failing*, and marks the home finished once its call ends, whether it returns or raises.

    A home's start marker, at start_marker(marker_dir, <home name>), and its finish marker, at
    finish_marker(marker_dir, <home name>), each appear at that path only once whole: each is written
    under a temporary name that carries the writer's process id and thread id, since two pool workers,
    or two threads of one process, can mark homes of one name at once, and then renamed. The finish
    marker is written before the home's results or exception leave the call, so before a pool worker
    sends them back.

    Each (name, path) pair in *held_until* holds the home of that name: it is marked, then waits until
    the path exists; if the path has not appeared within *hold_limit_seconds*, it raises TimeoutError
    naming the home and the path.

    A home it does not refuse gets make_sim_results(self_kwh=<its PV kW>, days=1), so the
    results total the home's PV kW of self-consumption, which identifies the home.
    """

    marker_dir: Path
    failing: frozenset[str] = frozenset()
    seconds: float = 0.0
    held_until: tuple[tuple[str, Path], ...] = ()
    hold_limit_seconds: float = 120.0

    def __call__(
        self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, weather: WeatherProvider
    ) -> SimulationResults:
        """Mark config's home as started, wait, then raise ValueError naming a failing home, else return its results; either way, mark the home finished as the call ends."""
        locations = [location.name for location in weather.frames] if isinstance(weather, PrefetchedWeather) else None
        _write_whole(
            start_marker(self.marker_dir, config.name), json.dumps({"pid": os.getpid(), "locations": locations})
        )
        try:
            release = dict(self.held_until).get(config.name)
            if release is not None:
                _wait_until_exists(release, config.name, self.hold_limit_seconds)
            time.sleep(self.seconds)
            if config.name in self.failing:
                raise ValueError(f"{config.name} cannot be simulated")
            return make_sim_results(self_kwh=config.pv_config.capacity_kw, days=1)
        finally:
            _write_whole(finish_marker(self.marker_dir, config.name), "")


def _write_whole(path: Path, text: str) -> None:
    """Write *text* to *path*, which appears only once whole: written under a temporary name carrying this process's and thread's ids, then renamed onto *path*."""
    partial = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.partial")
    partial.write_text(text, encoding="utf-8")
    partial.replace(path)


def _wait_until_exists(release: Path, home_name: str, limit: float) -> None:
    """Return once *release* exists, polling it; raise TimeoutError naming *home_name*, *release* and *limit* once *limit* seconds pass without it."""
    deadline = time.monotonic() + limit
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{home_name} was held until {release} existed, which it did not within {limit} s")
        time.sleep(0.01)


def start_marker(marker_dir: Path, home_name: str) -> Path:
    """The path at which a MarkingHomeSimulator over *marker_dir* marks the home *home_name* started, which appears only once whole, e.g. for another home's held_until."""
    return marker_dir / f"{home_name}{_STARTED_SUFFIX}"


def finish_marker(marker_dir: Path, home_name: str) -> Path:
    """The path at which a MarkingHomeSimulator over *marker_dir* marks the home *home_name* finished, which appears only once whole, e.g. for another home's held_until."""
    return marker_dir / f"{home_name}{_FINISHED_SUFFIX}"


def started(marker_dir: Path) -> dict[str, HomeStart]:
    """Each home a MarkingHomeSimulator over *marker_dir* started, by name, with what it recorded as the home started.

    It is safe to call while a MarkingHomeSimulator is still marking homes, in pool workers or other
    threads, because each marker appears at its name only when whole.
    """
    starts: dict[str, HomeStart] = {}
    for marker in sorted(marker_dir.glob(f"*{_STARTED_SUFFIX}")):
        recorded = json.loads(marker.read_text(encoding="utf-8"))
        locations = recorded["locations"]
        starts[marker.stem] = HomeStart(pid=recorded["pid"], locations=None if locations is None else tuple(locations))
    return starts


def wait_until_started(marker_dir: Path, homes: int, *, within: float) -> dict[str, HomeStart]:
    """started(*marker_dir*) as soon as it names at least *homes* homes, polling it; TimeoutError naming *homes*, *marker_dir*, *within* and the homes started once *within* seconds pass short of that.

    A test uses it to know a home is running before it ends a FleetRunner call.
    """
    deadline = time.monotonic() + within
    while len(starts := started(marker_dir)) < homes:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"{homes} homes had not started in {marker_dir} within {within} s; those started: {sorted(starts)}"
            )
        time.sleep(0.01)
    return starts


def finished(marker_dir: Path) -> frozenset[str]:
    """The name of each home a MarkingHomeSimulator over *marker_dir* has finished, whether it returned or raised.

    It is safe to call while a MarkingHomeSimulator is still marking homes, for the same reason
    started() is.
    """
    return frozenset(marker.name.removesuffix(_FINISHED_SUFFIX) for marker in marker_dir.glob(f"*{_FINISHED_SUFFIX}"))


@dataclass(frozen=True)
class ProcessEndingHomeSimulator:
    """A HomeSimulator that ends its worker process abruptly, as an out-of-memory kill would, at each home named in *ending*, and runs every other home as *marking* does.

    Called in the process that built it, it raises RuntimeError naming the home instead, so it cannot end a test run.
    """

    marking: MarkingHomeSimulator
    ending: frozenset[str]
    building_process: int = field(default_factory=os.getpid)

    def __call__(
        self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, weather: WeatherProvider
    ) -> SimulationResults:
        """Raise RuntimeError naming config's home in the building process; elsewhere end the process at a home named in ending, else return marking's results."""
        if os.getpid() == self.building_process:
            raise RuntimeError(
                f"{config.name}: ProcessEndingHomeSimulator ends the process it runs in, so it runs only in a pool's "
                "worker processes, never in the process that built it"
            )
        if config.name in self.ending:
            os._exit(70)
        return self.marking(config, start_date, end_date, weather=weather)

# SPDX-License-Identifier: AGPL-3.0-or-later
"""A home simulator for FleetRunner tests that marks each home it starts, so a test reads back which homes started, in which process, on which weather.

A FleetRunner's pool pickles its home simulator into each job, so a spawn or forkserver
worker imports this module to unpickle it. That is why the simulator is a top-level class
of a helper module rather than one defined in a test.

Usage::

    from tests._fleet_runner import MarkingHomeSimulator, started

    runner = FleetRunner(weather=weather, home_simulator=MarkingHomeSimulator(tmp_path, failing=frozenset({"Home 1"})))
    with pytest.raises(ValueError, match="Home 1 cannot be simulated"):
        runner.simulate(fleet, start, end)
    assert len(started(tmp_path)) < len(fleet.homes)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.weather import PrefetchedWeather, WeatherProvider
from tests._finance_builders import make_sim_results


@dataclass(frozen=True)
class HomeStart:
    """What MarkingHomeSimulator recorded as a home started: the id of the process it ran in, and the names of the locations its weather held, None for weather other than a PrefetchedWeather."""

    pid: int
    locations: tuple[str, ...] | None


@dataclass(frozen=True)
class MarkingHomeSimulator:
    """A HomeSimulator that marks each home it starts in *marker_dir*, waits *seconds*, then refuses each home named in *failing*.

    A home it does not refuse gets make_sim_results(self_kwh=<its PV kW>, days=1), so the
    results total the home's PV kW of self-consumption, which identifies the home.
    """

    marker_dir: Path
    failing: frozenset[str] = frozenset()
    seconds: float = 0.0

    def __call__(
        self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, weather: WeatherProvider
    ) -> SimulationResults:
        """Mark config's home as started, wait, then raise ValueError naming a failing home, else return its results."""
        locations = [location.name for location in weather.frames] if isinstance(weather, PrefetchedWeather) else None
        (self.marker_dir / f"{config.name}.json").write_text(
            json.dumps({"pid": os.getpid(), "locations": locations}), encoding="utf-8"
        )
        time.sleep(self.seconds)
        if config.name in self.failing:
            raise ValueError(f"{config.name} cannot be simulated")
        return make_sim_results(self_kwh=config.pv_config.capacity_kw, days=1)


def started(marker_dir: Path) -> dict[str, HomeStart]:
    """Each home a MarkingHomeSimulator over *marker_dir* started, by name, with what it recorded as the home started."""
    starts: dict[str, HomeStart] = {}
    for marker in sorted(marker_dir.glob("*.json")):
        recorded = json.loads(marker.read_text(encoding="utf-8"))
        locations = recorded["locations"]
        starts[marker.stem] = HomeStart(pid=recorded["pid"], locations=None if locations is None else tuple(locations))
    return starts

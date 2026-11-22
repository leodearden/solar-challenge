# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stand-ins for the simulation, the runner, the id source and the run store a JobManager is given."""

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from solar_challenge.fleet import FleetConfig, FleetResults, HomesDone
from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.weather import WeatherProvider
from solar_challenge.web.database import Database
from solar_challenge.web.storage import RunStorage


def _an_hour_at(generation_kw: float) -> SimulationResults:
    index = pd.date_range("2024-06-01 12:00", periods=60, freq="1min")

    def constant(kw: float) -> pd.Series:
        return pd.Series([kw] * 60, index=index)

    return SimulationResults(
        generation=constant(generation_kw),
        demand=constant(1.0),
        self_consumption=constant(1.0),
        battery_charge=constant(0.0),
        battery_discharge=constant(0.0),
        battery_soc=constant(0.0),
        grid_import=constant(0.0),
        grid_export=constant(generation_kw - 1.0),
        import_cost=constant(0.0),
        export_revenue=constant(0.0),
        tariff_rate=constant(0.25),
    )


class RecordingSimulation:
    """Stands in for simulate_home: records each home it is asked to simulate and returns an hour at the home's PV size, ignoring the weather."""

    def __init__(self) -> None:
        self.calls: list[tuple[HomeConfig, pd.Timestamp, pd.Timestamp]] = []

    def __call__(
        self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, weather: WeatherProvider
    ) -> SimulationResults:
        self.calls.append((config, start_date, end_date))
        return _an_hour_at(config.pv_config.capacity_kw)


def a_failing_simulation(
    config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, weather: WeatherProvider
) -> SimulationResults:
    """Stands in for simulate_home: every job it runs fails."""
    raise RuntimeError("the simulation failed")


@dataclass(frozen=True)
class FleetCall:
    """A simulate call RecordingFleetSimulator recorded: the fleet, its window and the progress sink it was given."""

    fleet: FleetConfig
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    progress: HomesDone | None


class RecordingFleetSimulator:
    """Stands in for a JobManager's runner: records each simulate call in fleet_calls and each simulate_home call in home_calls, and answers each home with an hour at its PV size.

    simulate answers a fleet with FleetResults pairing those hours with the fleet's homes, kept in answers.
    """

    def __init__(self) -> None:
        self.fleet_calls: list[FleetCall] = []
        self.home_calls: list[tuple[HomeConfig, pd.Timestamp, pd.Timestamp]] = []
        self.answers: list[FleetResults] = []

    def simulate(
        self, fleet: FleetConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, progress: HomesDone | None = None
    ) -> FleetResults:
        self.fleet_calls.append(FleetCall(fleet, start_date, end_date, progress))
        self.answers.append(
            FleetResults(
                per_home_results=tuple(_an_hour_at(home.pv_config.capacity_kw) for home in fleet.homes),
                home_configs=fleet.homes,
            )
        )
        return self.answers[-1]

    def simulate_each(
        self,
        fleets: Sequence[FleetConfig],
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        *,
        progress: HomesDone | None = None,
    ) -> Iterator[tuple[int, FleetResults]]:
        raise NotImplementedError("a JobManager's jobs simulate one fleet or one home at a time")

    def simulate_home(self, home: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
        self.home_calls.append((home, start_date, end_date))
        return _an_hour_at(home.pv_config.capacity_kw)


class BlockingSimulation:
    """Stands in for simulate_home: records each home it is asked to simulate, as RecordingSimulation does, then every job waits inside the simulation until release(), then gets an hour at its home's PV size.

    wait_until_started() returns once the first job is inside the simulation.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[HomeConfig, pd.Timestamp, pd.Timestamp]] = []
        self._started = threading.Event()
        self._released = threading.Event()

    def __call__(
        self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, weather: WeatherProvider
    ) -> SimulationResults:
        self.calls.append((config, start_date, end_date))
        self._started.set()
        self._released.wait()
        return _an_hour_at(config.pv_config.capacity_kw)

    def wait_until_started(self) -> None:
        if not self._started.wait(timeout=30):
            pytest.fail("no job entered the simulation within 30 s")

    def release(self) -> None:
        self._released.set()


class SteppedSimulation:
    """Stands in for simulate_home: records each home it is asked to simulate, as RecordingSimulation does, then holds it until allow_one() lets one held home finish with an hour at its PV size.

    wait_until_entered(count) returns once *count* homes have entered the simulation. A home held for 30 s raises TimeoutError, which fails its job, so a test that stops early never leaves a job waiting for good.
    """

    _HOLD_LIMIT_SECONDS = 30.0

    def __init__(self) -> None:
        self.calls: list[tuple[HomeConfig, pd.Timestamp, pd.Timestamp]] = []
        self._entered = threading.Condition()
        self._finishes = threading.Semaphore(0)

    def __call__(
        self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp, *, weather: WeatherProvider
    ) -> SimulationResults:
        with self._entered:
            self.calls.append((config, start_date, end_date))
            self._entered.notify_all()
        if not self._finishes.acquire(timeout=self._HOLD_LIMIT_SECONDS):
            raise TimeoutError(f"{config.name} was held for {self._HOLD_LIMIT_SECONDS} s with no allow_one()")
        return _an_hour_at(config.pv_config.capacity_kw)

    def allow_one(self) -> None:
        self._finishes.release()

    def wait_until_entered(self, count: int) -> None:
        with self._entered:
            if not self._entered.wait_for(lambda: len(self.calls) >= count, timeout=30):
                pytest.fail(f"{count} homes had not entered the simulation within 30 s; {len(self.calls)} had")


class SaveGate:
    """Holds each save that waits at it until open(): hold() marks a save as waiting, then waits until open().

    wait_until_a_save_waits() returns once a save waits at the gate.
    """

    def __init__(self) -> None:
        self._waiting = threading.Event()
        self._opened = threading.Event()

    def hold(self) -> None:
        self._waiting.set()
        self._opened.wait()

    def wait_until_a_save_waits(self) -> None:
        if not self._waiting.wait(timeout=30):
            pytest.fail("no save waited at the gate within 30 s")

    def open(self) -> None:
        self._opened.set()


class RunStorageWithGatedHomeSaves(RunStorage):
    """Stands in for a JobManager's RunStorage: each home job's final save waits at *gate* until it opens, then saves as RunStorage does."""

    def __init__(self, database: Database, data_dir: str | Path, gate: SaveGate) -> None:
        super().__init__(database, data_dir)
        self._gate = gate

    def save_home_run_from_results(
        self, run_id: str, config: HomeConfig, results: SimulationResults, **save: Any
    ) -> None:
        self._gate.hold()
        super().save_home_run_from_results(run_id, config, results, **save)


class RunStorageRefusingCompletion(RunStorage):
    """Stands in for a JobManager's RunStorage whose database refuses to record a run completed: mark_run_completed raises sqlite3.OperationalError and writes nothing."""

    def mark_run_completed(self, run_id: str) -> None:
        raise sqlite3.OperationalError("the database refuses to complete runs")


class RunStorageWithGatedCompletion(RunStorage):
    """Stands in for a JobManager's RunStorage: each job's run is marked completed as RunStorage marks it, then the job waits at *gate* until it opens."""

    def __init__(self, database: Database, data_dir: str | Path, gate: SaveGate) -> None:
        super().__init__(database, data_dir)
        self._gate = gate

    def mark_run_completed(self, run_id: str) -> None:
        super().mark_run_completed(run_id)
        self._gate.hold()


class CountingIds:
    """Stands in for a JobManager's id source: issues "id-1", "id-2", ... and keeps every id it issued."""

    def __init__(self) -> None:
        self.issued: list[str] = []

    def __call__(self) -> str:
        self.issued.append(f"id-{len(self.issued) + 1}")
        return self.issued[-1]

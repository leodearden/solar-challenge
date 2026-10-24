# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stand-ins for the simulation, the id source and the run store a JobManager is given."""

import threading
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from solar_challenge.home import HomeConfig, SimulationResults
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
    """Stands in for simulate_home: records each home it is asked to simulate and returns an hour at the home's PV size."""

    def __init__(self) -> None:
        self.calls: list[tuple[HomeConfig, pd.Timestamp, pd.Timestamp]] = []

    def __call__(self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
        self.calls.append((config, start_date, end_date))
        return _an_hour_at(config.pv_config.capacity_kw)


def a_failing_simulation(config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
    """Stands in for simulate_home: every job it runs fails."""
    raise RuntimeError("the simulation failed")


class BlockingSimulation:
    """Stands in for simulate_home: records each home it is asked to simulate, as RecordingSimulation does, then every job waits inside the simulation until release(), then gets an hour at its home's PV size.

    wait_until_started() returns once the first job is inside the simulation.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[HomeConfig, pd.Timestamp, pd.Timestamp]] = []
        self._started = threading.Event()
        self._released = threading.Event()

    def __call__(self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
        self.calls.append((config, start_date, end_date))
        self._started.set()
        self._released.wait()
        return _an_hour_at(config.pv_config.capacity_kw)

    def wait_until_started(self) -> None:
        if not self._started.wait(timeout=30):
            pytest.fail("no job entered the simulation within 30 s")

    def release(self) -> None:
        self._released.set()


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


class CountingIds:
    """Stands in for a JobManager's id source: issues "id-1", "id-2", ... and keeps every id it issued."""

    def __init__(self) -> None:
        self.issued: list[str] = []

    def __call__(self) -> str:
        self.issued.append(f"id-{len(self.issued) + 1}")
        return self.issued[-1]

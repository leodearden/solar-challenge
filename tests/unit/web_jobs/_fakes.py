# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stand-ins for the simulation and the id source a JobManager is given."""

import threading

import pandas as pd
import pytest

from solar_challenge.home import HomeConfig, SimulationResults


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


class CountingIds:
    """Stands in for a JobManager's id source: issues "id-1", "id-2", ... and keeps every id it issued."""

    def __init__(self) -> None:
        self.issued: list[str] = []

    def __call__(self) -> str:
        self.issued.append(f"id-{len(self.issued) + 1}")
        return self.issued[-1]

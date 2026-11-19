# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_fleet_runner.py, the home simulators through which FleetRunner tests read back which homes started and finished, or break a pool."""

import concurrent.futures
import multiprocessing
import os
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest
from solar_challenge.home import HomeConfig, calculate_summary
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.weather import PrefetchedWeather
from tests._fleet_runner import HomeStart, MarkingHomeSimulator, ProcessEndingHomeSimulator, finished, started

_DAY = pd.Timestamp("2024-06-21")
_BRISTOL_ONLY = PrefetchedWeather({Location.bristol(): pd.DataFrame()})
"""MarkingHomeSimulator reads only the location keys of its weather's frames, never a frame, so an empty frame is enough."""
_HELD = HomeConfig(
    pv_config=PVConfig(capacity_kw=4.0),
    load_config=LoadConfig(annual_consumption_kwh=3500.0, use_stochastic=False),
    name="Held",
)


def _mark_each(simulator: MarkingHomeSimulator, homes: Sequence[HomeConfig]) -> None:
    """Start each of *homes* once through *simulator*, so that it writes each home's marker."""
    for home in homes:
        simulator(home, _DAY, _DAY, weather=_BRISTOL_ONLY)


def _re_mark_until(simulator: MarkingHomeSimulator, homes: Sequence[HomeConfig], stop: threading.Event) -> None:
    """Mark *homes* again, round after round, until *stop* is set."""
    while not stop.is_set():
        _mark_each(simulator, homes)


@pytest.mark.parametrize("re_marking_threads", [1, 2], ids=["one-thread", "two-threads"])
def test_started_and_finished_read_while_other_threads_re_mark_the_homes_see_each_marker_whole(
    tmp_path: Path, re_marking_threads: int
) -> None:
    """Two threads re-marking one home name are two writers of its marker, as two pool workers are when two fleets share home names."""
    homes = [
        HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3500.0, use_stochastic=False),
            name=f"Home {n}",
        )
        for n in range(1, 5)
    ]
    simulator = MarkingHomeSimulator(tmp_path)
    _mark_each(simulator, homes)
    every_home_whole = {home.name: HomeStart(pid=os.getpid(), locations=("Bristol, UK",)) for home in homes}
    every_home_finished = frozenset(home.name for home in homes)

    stop = threading.Event()
    with ThreadPoolExecutor(max_workers=re_marking_threads) as re_marking:
        re_marked = [re_marking.submit(_re_mark_until, simulator, homes, stop) for _ in range(re_marking_threads)]
        try:
            readings = [(started(tmp_path), finished(tmp_path)) for _ in range(1000)]
        finally:
            stop.set()
        for re_marked_by_one_thread in re_marked:
            re_marked_by_one_thread.result()

    assert [reading for reading in readings if reading != (every_home_whole, every_home_finished)] == []
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        marker for home in homes for marker in (f"{home.name}.json", f"{home.name}.finished")
    )


def _started_once_a_home_is_marked(marker_dir: Path, *, within: float) -> dict[str, HomeStart]:
    """started(*marker_dir*) as soon as it names a home, polling it, or once *within* seconds pass with none, whichever comes first."""
    deadline = time.monotonic() + within
    while not (starts := started(marker_dir)) and time.monotonic() < deadline:
        time.sleep(0.01)
    return starts


def test_a_home_named_in_held_until_is_marked_started_then_waits_until_its_release_exists_to_finish(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    simulator = MarkingHomeSimulator(tmp_path, held_until=(("Held", release),))

    with ThreadPoolExecutor(max_workers=1) as holding:
        held = holding.submit(simulator, _HELD, _DAY, _DAY, weather=_BRISTOL_ONLY)
        with pytest.raises(concurrent.futures.TimeoutError):
            held.result(timeout=0.2)
        marked_while_held = set(_started_once_a_home_is_marked(tmp_path, within=10))
        finished_while_held = finished(tmp_path)
        release.touch()
        results = held.result(timeout=10)

    assert marked_while_held == {"Held"}
    assert finished_while_held == frozenset()
    assert finished(tmp_path) == {"Held"}
    assert calculate_summary(results).total_self_consumption_kwh == pytest.approx(4.0)


def test_a_home_whose_release_never_appears_raises_timeout_error_naming_it_and_its_release(tmp_path: Path) -> None:
    never = tmp_path / "never"
    simulator = MarkingHomeSimulator(tmp_path, held_until=(("Held", never),), hold_limit_seconds=0.05)

    with pytest.raises(TimeoutError) as caught:
        simulator(_HELD, _DAY, _DAY, weather=_BRISTOL_ONLY)

    assert str(caught.value) == f"Held was held until {never} existed, which it did not within 0.05 s"
    assert finished(tmp_path) == {"Held"}


@pytest.mark.parametrize("failing", [frozenset(), frozenset({"Held"})], ids=["returns", "refused"])
def test_a_refused_home_is_marked_finished_as_a_home_that_returns_is(tmp_path: Path, failing: frozenset[str]) -> None:
    simulator = MarkingHomeSimulator(tmp_path, failing=failing)

    if failing:
        with pytest.raises(ValueError, match="Held cannot be simulated"):
            simulator(_HELD, _DAY, _DAY, weather=_BRISTOL_ONLY)
    else:
        simulator(_HELD, _DAY, _DAY, weather=_BRISTOL_ONLY)

    assert finished(tmp_path) == {"Held"}


def test_a_process_ending_simulator_refuses_to_run_in_the_process_that_built_it_even_at_a_home_it_ends(
    tmp_path: Path,
) -> None:
    simulator = ProcessEndingHomeSimulator(MarkingHomeSimulator(tmp_path), ending=frozenset({"Held"}))

    with pytest.raises(RuntimeError) as caught:
        simulator(_HELD, _DAY, _DAY, weather=_BRISTOL_ONLY)

    assert str(caught.value) == (
        "Held: ProcessEndingHomeSimulator ends the process it runs in, so it runs only in a pool's "
        "worker processes, never in the process that built it"
    )
    assert started(tmp_path) == {}
    assert finished(tmp_path) == frozenset()


def test_a_process_ending_simulator_in_a_worker_process_runs_a_home_it_does_not_end_as_marking_does(
    tmp_path: Path,
) -> None:
    simulator = ProcessEndingHomeSimulator(MarkingHomeSimulator(tmp_path), ending=frozenset({"Ended"}))

    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("forkserver")) as worker:
        worker_pid = worker.submit(os.getpid).result()
        results = worker.submit(simulator, _HELD, _DAY, _DAY, weather=_BRISTOL_ONLY).result()

    assert started(tmp_path) == {"Held": HomeStart(pid=worker_pid, locations=("Bristol, UK",))}
    assert calculate_summary(results).total_self_consumption_kwh == pytest.approx(4.0)

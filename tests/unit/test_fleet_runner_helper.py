# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_fleet_runner.py, the home simulator through which FleetRunner tests read back which homes started."""

import concurrent.futures
import os
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest
from solar_challenge.home import HomeConfig, calculate_summary
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.weather import PrefetchedWeather
from tests._fleet_runner import HomeStart, MarkingHomeSimulator, started

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
def test_started_read_while_other_threads_re_mark_the_homes_sees_each_marker_whole(
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

    stop = threading.Event()
    with ThreadPoolExecutor(max_workers=re_marking_threads) as re_marking:
        re_marked = [re_marking.submit(_re_mark_until, simulator, homes, stop) for _ in range(re_marking_threads)]
        try:
            readings = [started(tmp_path) for _ in range(1000)]
        finally:
            stop.set()
        for re_marked_by_one_thread in re_marked:
            re_marked_by_one_thread.result()

    assert [reading for reading in readings if reading != every_home_whole] == []
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(f"{home.name}.json" for home in homes)


def _started_once_a_home_is_marked(marker_dir: Path, *, within: float) -> dict[str, HomeStart]:
    """started(*marker_dir*) as soon as it names a home, polling it, or once *within* seconds pass with none, whichever comes first."""
    deadline = time.monotonic() + within
    while not (starts := started(marker_dir)) and time.monotonic() < deadline:
        time.sleep(0.01)
    return starts


def test_a_home_named_in_held_until_is_marked_then_waits_until_its_release_exists(tmp_path: Path) -> None:
    release = tmp_path / "release"
    simulator = MarkingHomeSimulator(tmp_path, held_until={"Held": release})

    with ThreadPoolExecutor(max_workers=1) as holding:
        held = holding.submit(simulator, _HELD, _DAY, _DAY, weather=_BRISTOL_ONLY)
        with pytest.raises(concurrent.futures.TimeoutError):
            held.result(timeout=0.2)
        marked_while_held = set(_started_once_a_home_is_marked(tmp_path, within=10))
        release.touch()
        results = held.result(timeout=10)

    assert marked_while_held == {"Held"}
    assert calculate_summary(results).total_self_consumption_kwh == pytest.approx(4.0)


def test_a_home_whose_release_never_appears_raises_timeout_error_naming_it_and_its_release(tmp_path: Path) -> None:
    never = tmp_path / "never"
    simulator = MarkingHomeSimulator(tmp_path, held_until={"Held": never}, hold_limit_seconds=0.05)

    with pytest.raises(TimeoutError) as caught:
        simulator(_HELD, _DAY, _DAY, weather=_BRISTOL_ONLY)

    assert str(caught.value) == f"Held was held until {never} existed, which it did not within 0.05 s"

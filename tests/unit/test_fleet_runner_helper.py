# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_fleet_runner.py, the home simulator through which FleetRunner tests read back which homes started."""

import os
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.weather import PrefetchedWeather
from tests._fleet_runner import HomeStart, MarkingHomeSimulator, started

_DAY = pd.Timestamp("2024-06-21")
_BRISTOL_ONLY = PrefetchedWeather({Location.bristol(): pd.DataFrame()})
"""MarkingHomeSimulator reads only the location keys of its weather's frames, never a frame, so an empty frame is enough."""


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

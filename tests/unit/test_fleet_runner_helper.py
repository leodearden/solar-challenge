# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_fleet_runner.py, the home simulator through which FleetRunner tests read back which homes started."""

import os
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
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


def test_started_read_while_another_thread_re_marks_the_homes_sees_each_marker_whole(tmp_path: Path) -> None:
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
    with ThreadPoolExecutor(max_workers=1) as re_marking:
        re_marked = re_marking.submit(_re_mark_until, simulator, homes, stop)
        try:
            readings = [started(tmp_path) for _ in range(1000)]
        finally:
            stop.set()
        re_marked.result()

    assert [reading for reading in readings if reading != every_home_whole] == []

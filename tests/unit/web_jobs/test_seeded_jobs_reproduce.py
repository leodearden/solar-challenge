# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seeded home jobs run together on the dashboard's job manager store the demand a serial run of each gives."""

import functools
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("flask")

from solar_challenge.home import HomeConfig, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.weather import WeatherCache, default_weather
from solar_challenge.web.jobs import JobManager
from tests._run_stores import empty_run_storage
from tests._synthetic_weather import synthetic_june_weather


def test_two_seeded_home_jobs_run_together_store_the_demand_a_serial_run_gives(
    weather_cache: WeatherCache, tmp_path: Path
) -> None:
    weather_cache.put(synthetic_june_weather("2024-06-01", (1.0,) * 7), "tmy", Location.bristol())
    homes = {
        seed: HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3400, seed=seed),
        )
        for seed in (42, 43)
    }
    start, end = pd.Timestamp("2024-06-01"), pd.Timestamp("2024-06-07")
    serial = {
        seed: simulate_home(home, start, end, weather=default_weather()).demand
        for seed, home in homes.items()
    }
    assert not serial[42].equals(serial[43]), (
        "seeds 42 and 43 gave one demand, so neither home's load is stochastic"
    )

    storage = empty_run_storage(tmp_path)
    manager = JobManager(
        storage, max_workers=2, simulate_home=functools.partial(simulate_home, weather=default_weather())
    )
    differing = []
    for trial in range(2):
        jobs = {seed: manager.submit_home_job(home, start, end) for seed, home in homes.items()}
        assert manager.wait_until_idle(timeout=120)
        for seed, (job_id, run_id) in jobs.items():
            state = manager.job_state(job_id)
            assert state is not None and state.status == "completed", state
            if not storage.load_run(run_id).results.demand.equals(serial[seed]):
                differing.append((trial, seed))

    assert differing == []

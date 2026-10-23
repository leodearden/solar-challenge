# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins that tests/e2e/conftest.py seeds the weather its live server's jobs simulate on: they complete offline at every location preset the dashboard offers, a heat pump's included, and leave no weather cache behind.

The scenario runs in a session of its own, laid out as the e2e suite is: under a
copy of tests/conftest.py, with a copy of the e2e conftest in e2e/. The session
names that directory, as the offline lane's e2e job names tests/e2e, because the
root conftest's collect_ignore keeps it out of any other collection. Like the
lane's, it starts with no weather cache directory named, not with the variable of
the window that runs the test here.
"""

from pathlib import Path

import pytest

from solar_challenge.weather import CACHE_DIR_VARIABLE, DEFAULT_CACHE_DIR

pytest.importorskip("flask")

HOME_JOBS_AT_EVERY_LOCATION_PRESET = """
    import json
    import urllib.request

    from solar_challenge.web.request_boundary import LOCATION_PRESETS

    HOME_JOBS = {
        **{location: {"location": location, "days": 1} for location in LOCATION_PRESETS},
        "heat pump": {"location": "bristol", "days": 1, "heat_pump": {"type": "ASHP"}},
    }

    job_ids = {}


    def test_submits_each_home_job(live_server):
        for name, body in HOME_JOBS.items():
            request = urllib.request.Request(
                live_server + "/api/simulate/home",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                job_ids[name] = json.load(response)["job_id"]


    def test_every_job_has_completed(live_server):
        statuses = {}
        for name, job_id in job_ids.items():
            with urllib.request.urlopen(live_server + f"/api/jobs/{job_id}", timeout=30) as response:
                statuses[name] = json.load(response)["status"]

        assert statuses == dict.fromkeys(HOME_JOBS, "completed")
    """


def test_the_live_servers_jobs_at_every_location_preset_complete_offline_and_leave_no_weather_cache_behind(
    pytester_under_root_conftest: pytest.Pytester, e2e_conftest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A heat pump shares its annual heat demand out over a whole year of weather, so its job completes only on a whole TMY year."""
    monkeypatch.delenv(CACHE_DIR_VARIABLE, raising=False)
    pytester_under_root_conftest.makepyfile(
        **{
            "e2e/conftest": e2e_conftest.read_text(encoding="utf-8"),
            "e2e/test_home_jobs_at_every_location_preset": HOME_JOBS_AT_EVERY_LOCATION_PRESET,
        }
    )

    result = pytester_under_root_conftest.runpytest_subprocess("-p", "no:cacheprovider", "e2e")

    result.assert_outcomes(passed=2)
    assert not (pytester_under_root_conftest.path / DEFAULT_CACHE_DIR).exists()

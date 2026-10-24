# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins on the weather tests/e2e/conftest.py gives its live server's jobs.

- The jobs complete offline at every location preset the dashboard offers, a
  heat pump's included, and leave no weather cache behind.
- They simulate on the WeatherCache that a test module's override of
  live_server_weather returns.
- A session whose last test is slow leaves CACHE_DIR_VARIABLE at
  pytest_sessionfinish with the value it had before the session.

Each scenario runs in a session of its own, laid out as the offline lane's e2e
job runs tests/e2e: copies of pyproject.toml and tests/conftest.py, with the e2e
conftest's copy in e2e/. An override changes the app of the whole session, and
the slow test must run last, so no two scenarios share one. The session names
e2e/, as the lane's job names tests/e2e, because the root conftest's
collect_ignore keeps it out of any other collection. Like the lane's, it starts
with no weather cache directory named, not with the variable of the window that
runs the test here.
"""

import json
import os
from pathlib import Path

import pytest

from solar_challenge.weather import CACHE_DIR_VARIABLE, DEFAULT_CACHE_DIR

pytest.importorskip("flask")


@pytest.fixture
def pytester_laid_out_as_the_e2e_suite(
    pytester_under_root_conftest: pytest.Pytester,
    project_root: Path,
    e2e_conftest: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> pytest.Pytester:
    """pytester_under_root_conftest, with a copy of pyproject.toml beside the root conftest's and the e2e conftest's copy in e2e/.

    Its sessions start with no weather cache directory named.
    """
    monkeypatch.delenv(CACHE_DIR_VARIABLE, raising=False)
    pytester_under_root_conftest.makepyprojecttoml((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    pytester_under_root_conftest.makepyfile(**{"e2e/conftest": e2e_conftest.read_text(encoding="utf-8")})
    return pytester_under_root_conftest


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
    pytester_laid_out_as_the_e2e_suite: pytest.Pytester,
) -> None:
    """A heat pump shares its annual heat demand out over a whole year of weather, so its job completes only on a whole TMY year."""
    pytester_laid_out_as_the_e2e_suite.makepyfile(
        **{"e2e/test_home_jobs_at_every_location_preset": HOME_JOBS_AT_EVERY_LOCATION_PRESET}
    )

    result = pytester_laid_out_as_the_e2e_suite.runpytest_subprocess("-p", "no:cacheprovider", "e2e")

    result.assert_outcomes(passed=2)
    assert not (pytester_laid_out_as_the_e2e_suite.path / DEFAULT_CACHE_DIR).exists()


A_HOME_JOB_ON_A_SUNLESS_OVERRIDE = """
    import json
    import urllib.request

    import pytest

    from solar_challenge.weather import WeatherCache
    from solar_challenge.web.request_boundary import LOCATION_PRESETS

    from tests._synthetic_weather import TMY_DAYS, synthetic_tmy

    job_ids = []


    @pytest.fixture(scope="session")
    def live_server_weather(tmp_path_factory):
        cache = WeatherCache(cache_dir=tmp_path_factory.mktemp("sunless-weather"))
        cache.put(synthetic_tmy(irradiance_scale_per_day=(0.0,) * TMY_DAYS), "tmy", LOCATION_PRESETS["bristol"])
        return cache


    def test_submits_a_home_job_at_bristol(live_server):
        request = urllib.request.Request(
            live_server + "/api/simulate/home",
            data=json.dumps({"location": "bristol", "days": 1}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            job_ids.append(json.load(response)["job_id"])


    def test_the_home_generated_nothing(live_server):
        job_id = job_ids[0]

        with urllib.request.urlopen(live_server + f"/api/jobs/{job_id}/results", timeout=30) as response:
            summary = json.load(response)["summary"]

        assert summary["total_generation_kwh"] == 0
    """


def test_the_live_servers_jobs_simulate_on_the_weather_cache_a_test_modules_override_of_live_server_weather_returns(
    pytester_laid_out_as_the_e2e_suite: pytest.Pytester,
) -> None:
    """The override's TMY is sunless, so the home generates nothing on it, where the conftest's own clear TMY gives it sun."""
    pytester_laid_out_as_the_e2e_suite.makepyfile(
        **{"e2e/test_a_home_job_on_a_sunless_override": A_HOME_JOB_ON_A_SUNLESS_OVERRIDE}
    )

    result = pytester_laid_out_as_the_e2e_suite.runpytest_subprocess("-p", "no:cacheprovider", "e2e")

    result.assert_outcomes(passed=2)


RECORDS_THE_VARIABLE = """
    import json
    import os

    from solar_challenge.weather import CACHE_DIR_VARIABLE


    def pytest_sessionfinish(session):
        record = session.config.invocation_params.dir / "variable_at_sessionfinish.json"
        record.write_text(json.dumps(os.environ.get(CACHE_DIR_VARIABLE)), encoding="utf-8")
    """

THE_LAST_OF_THEM_SLOW = """
    import pytest


    def test_a_fast_test_runs_first(live_server):
        pass


    @pytest.mark.slow
    def test_a_slow_test_runs_last(live_server):
        pass
    """


def test_a_session_whose_last_test_is_slow_leaves_the_weather_cache_variable_as_it_found_it(
    pytester_laid_out_as_the_e2e_suite: pytest.Pytester,
) -> None:
    """No offline window wraps the slow last test, whose teardown tears the session's fixtures down, so no window puts the variable back after them.

    The variable is read at pytest_sessionfinish by a plugin the session loads, records_the_variable, which is no test module and so is never collected.
    """
    pytester_laid_out_as_the_e2e_suite.makepyfile(
        records_the_variable=RECORDS_THE_VARIABLE,
        **{"e2e/test_the_last_of_them_slow": THE_LAST_OF_THEM_SLOW},
    )
    variable_before_the_session = os.environ.get(CACHE_DIR_VARIABLE)

    result = pytester_laid_out_as_the_e2e_suite.runpytest_subprocess(
        "-p", "no:cacheprovider", "-p", "records_the_variable", "e2e"
    )

    result.assert_outcomes(passed=2)
    record = pytester_laid_out_as_the_e2e_suite.path / "variable_at_sessionfinish.json"
    variable_at_sessionfinish = json.loads(record.read_text(encoding="utf-8"))
    assert variable_at_sessionfinish == variable_before_the_session

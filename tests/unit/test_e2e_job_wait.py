"""Pins that tests/e2e/conftest.py lets no test's live-server jobs run on into the next test.

What one test's teardown did is only visible from a later test, so the scenarios
run in order inside a separate pytest session under a copy of the e2e conftest.
The job must complete: a failing job can end before the next test starts even
with no wait, so a 'failed' status would not show that the wait happened.
"""

import os
from pathlib import Path

import pytest
pytest.importorskip("flask")

pytest_plugins = ["pytester"]

E2E_CONFTEST = Path(__file__).parents[1] / "e2e" / "conftest.py"

SCENARIOS = """
    import json
    import urllib.request

    import pytest

    from solar_challenge.location import Location
    from solar_challenge.weather import WeatherCache, set_weather_cache

    from tests._synthetic_weather import synthetic_june_weather

    HOME_JOB = {"pv_kw": 4.0, "battery_kwh": 0, "occupants": 3, "location": "bristol", "days": 1}

    LOCALHOST = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    jobs_submitted_by_earlier_tests = []


    # HOME_JOB simulates 1 June 2024, so Bristol's TMY is a clear day on that date.
    @pytest.fixture(autouse=True, scope="session")
    def _bristol_tmy(tmp_path_factory):
        cache = WeatherCache(cache_dir=tmp_path_factory.mktemp("weather"))
        cache.put(synthetic_june_weather("2024-06-01"), "tmy", Location.bristol())
        set_weather_cache(cache)
        yield
        set_weather_cache(None)


    def test_an_earlier_test_submits_a_job_and_ends_without_waiting_for_it(live_server):
        request = urllib.request.Request(
            live_server + "/api/simulate/home",
            data=json.dumps(HOME_JOB).encode(),
            headers={"Content-Type": "application/json"},
        )
        with LOCALHOST.open(request, timeout=30) as response:
            assert response.status == 201
            jobs_submitted_by_earlier_tests.append(json.load(response)["job_id"])


    def test_the_next_test_starts_after_that_job_has_completed(live_server):
        job_id = jobs_submitted_by_earlier_tests[0]

        with LOCALHOST.open(live_server + f"/api/jobs/{job_id}", timeout=30) as response:
            job = json.load(response)

        assert job["status"] == "completed", job
"""


def test_each_e2e_tests_live_server_jobs_finish_before_the_next_test_starts(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    project_root: Path,
) -> None:
    pytester.makeconftest(E2E_CONFTEST.read_text(encoding="utf-8"))
    scenarios = pytester.makepyfile(SCENARIOS)
    # The e2e conftest builds its app with tests/_web_app.py, whatever directory the suite runs from.
    monkeypatch.setenv("PYTHONPATH", str(project_root), prepend=os.pathsep)
    # A job that fetched its TMY goes through this dead proxy and fails, so the pin cannot pass by reaching PVGIS.
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)

    result = pytester.runpytest_subprocess(scenarios)

    result.assert_outcomes(passed=2)

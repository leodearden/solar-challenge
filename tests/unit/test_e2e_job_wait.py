"""Pins that tests/e2e/conftest.py lets no test's live-server jobs run on into the next test.

What one test's teardown did is only visible from a later test, so the scenarios
run in order inside a separate pytest session under a copy of the e2e conftest.
"""

from pathlib import Path

import pytest
pytest.importorskip("flask")

pytest_plugins = ["pytester"]

E2E_CONFTEST = Path(__file__).parents[1] / "e2e" / "conftest.py"

SCENARIOS = """
    import json
    import urllib.request

    HOME_JOB = {"pv_kw": 4.0, "battery_kwh": 0, "occupants": 3, "location": "bristol", "days": 1}

    LOCALHOST = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    jobs_submitted_by_earlier_tests = []


    def test_an_earlier_test_submits_a_job_and_ends_without_waiting_for_it(live_server):
        request = urllib.request.Request(
            live_server + "/api/simulate/home",
            data=json.dumps(HOME_JOB).encode(),
            headers={"Content-Type": "application/json"},
        )
        with LOCALHOST.open(request, timeout=30) as response:
            assert response.status == 201
            jobs_submitted_by_earlier_tests.append(json.load(response)["job_id"])


    def test_the_next_test_starts_after_that_job_has_finished(live_server):
        job_id = jobs_submitted_by_earlier_tests[0]

        with LOCALHOST.open(live_server + f"/api/jobs/{job_id}", timeout=30) as response:
            status = json.load(response)["status"]

        assert status in ("completed", "failed")
"""


def test_each_e2e_tests_live_server_jobs_finish_before_the_next_test_starts(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    pytester.makeconftest(E2E_CONFTEST.read_text(encoding="utf-8"))
    scenarios = pytester.makepyfile(SCENARIOS)
    # The scenarios' job reads the weather cache relative to cwd, so run where the suite runs.
    monkeypatch.chdir(request.config.invocation_params.dir)

    result = pytester.runpytest_subprocess(scenarios)

    result.assert_outcomes(passed=2)

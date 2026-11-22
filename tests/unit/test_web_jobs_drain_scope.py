"""Pins that the closing harness closes only what its builders built, and that nothing sweeps the rest.

A test's teardown closes each app tests/_web_app.py's app_builder built on the test's
closes_at_teardown stack, which tests/unit/conftest.py's build_app fixture is. An app a
broader-scoped fixture built is closed by that fixture's own teardown, and a JobManager a test
built itself, outside any harness, is shut down by nothing but that test (B15).

What one test's teardown did is only visible from a later test, so the scenarios
run in order inside a separate pytest session under a copy of the root conftest.
"""

import pytest
pytest.importorskip("flask")

SCENARIOS = """
    import pandas as pd
    import pytest

    from solar_challenge.home import HomeConfig
    from solar_challenge.load import LoadConfig
    from solar_challenge.pv import PVConfig
    from solar_challenge.web.dashboard import dashboard_of
    from solar_challenge.web.jobs import JobManager

    from tests._run_stores import empty_run_storage
    from tests._web_app import app_builder, build_test_app
    from tests._web_job_runner import jobs_running, runner_of

    HOME_JOB = {"pv_kw": 4.0, "battery_kwh": 0, "occupants": 3, "location": "bristol", "days": 1}

    apps_built_inside_earlier_tests = []
    managers_built_inside_earlier_tests = []


    def no_simulation(config, start_date, end_date, *, weather):
        raise RuntimeError("the drain-scope scenarios run no simulation")


    @pytest.fixture(scope="module")
    def module_app(tmp_path_factory):
        app = build_test_app(tmp_path_factory.mktemp("module_app"), jobs=jobs_running(no_simulation))
        yield app
        dashboard_of(app).close()


    def test_an_earlier_test_uses_the_module_app_and_builds_an_app_and_a_manager(
        module_app, closes_at_teardown, tmp_path
    ):
        assert module_app.test_client().get("/").status_code == 200

        apps_built_inside_earlier_tests.append(app_builder(closes_at_teardown)(tmp_path))
        managers_built_inside_earlier_tests.append(
            JobManager(empty_run_storage(tmp_path / "own_manager"), runner=runner_of(no_simulation))
        )


    def test_the_module_app_still_accepts_a_job_after_an_earlier_tests_teardown(module_app):
        response = module_app.test_client().post("/api/simulate/home", json=HOME_JOB)

        assert response.status_code == 201


    def test_an_app_the_harness_built_inside_an_earlier_test_was_closed_at_its_teardown():
        app_from_earlier_test = apps_built_inside_earlier_tests[0]

        with pytest.raises(RuntimeError, match="shutdown"):
            app_from_earlier_test.test_client().post("/api/simulate/home", json=HOME_JOB)


    def test_a_manager_an_earlier_test_built_itself_still_accepts_a_job_after_its_teardown():
        manager = managers_built_inside_earlier_tests[0]
        try:
            manager.submit_home_job(
                HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig(annual_consumption_kwh=3500)),
                pd.Timestamp("2024-06-01", tz="UTC"),
                pd.Timestamp("2024-06-02", tz="UTC"),
            )
        finally:
            manager.shutdown(wait=True)
"""


def test_the_closing_harness_closes_only_what_its_builders_built_and_nothing_sweeps_the_rest(
    pytester_under_root_conftest: pytest.Pytester,
) -> None:
    scenarios = pytester_under_root_conftest.makepyfile(SCENARIOS)

    result = pytester_under_root_conftest.runpytest_subprocess(scenarios)

    result.assert_outcomes(passed=4)

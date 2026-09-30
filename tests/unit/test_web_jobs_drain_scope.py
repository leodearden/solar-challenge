"""Pins that the per-test JobManager drain in tests/conftest.py stops only the managers a test created.

What one test's teardown did is only visible from a later test, so the scenarios
run in order inside a separate pytest session under a copy of the root conftest.
"""

import os
from pathlib import Path

import pytest
pytest.importorskip("flask")

pytest_plugins = ["pytester"]

ROOT_CONFTEST = Path(__file__).parents[1] / "conftest.py"

SCENARIOS = """
    import pytest

    from solar_challenge.web.shared import get_job_manager

    from tests._web_app import build_test_app

    HOME_JOB = {"pv_kw": 4.0, "battery_kwh": 0, "occupants": 3, "location": "bristol", "days": 1}

    apps_built_inside_earlier_tests = []


    @pytest.fixture(scope="module")
    def module_app(tmp_path_factory):
        app = build_test_app(tmp_path_factory.mktemp("module_app"))
        yield app
        with app.app_context():
            get_job_manager().shutdown(wait=True)


    def test_an_earlier_test_uses_the_module_app_and_builds_its_own_app(module_app, tmp_path):
        assert module_app.test_client().get("/").status_code == 200

        apps_built_inside_earlier_tests.append(build_test_app(tmp_path))


    def test_module_app_still_accepts_a_job_after_an_earlier_tests_teardown(module_app):
        response = module_app.test_client().post("/api/simulate/home", json=HOME_JOB)

        assert response.status_code == 201


    def test_an_app_built_inside_an_earlier_test_was_drained_at_its_teardown():
        app_from_earlier_test = apps_built_inside_earlier_tests[0]

        with pytest.raises(RuntimeError, match="shutdown"):
            app_from_earlier_test.test_client().post("/api/simulate/home", json=HOME_JOB)
"""


def test_the_per_test_drain_stops_only_the_managers_a_test_created(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    project_root: Path,
) -> None:
    pytester.makeconftest(ROOT_CONFTEST.read_text(encoding="utf-8"))
    scenarios = pytester.makepyfile(SCENARIOS)
    # The scenarios' job reads the weather cache relative to cwd, so run where the suite runs.
    monkeypatch.chdir(request.config.invocation_params.dir)
    # The scenarios build their apps with tests/_web_app.py, whatever directory the suite runs from.
    monkeypatch.setenv("PYTHONPATH", str(project_root), prepend=os.pathsep)

    result = pytester.runpytest_subprocess(scenarios)

    result.assert_outcomes(passed=3)

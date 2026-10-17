# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_scenario_session.py, which runs several scenario modules in one pytester session.

The scenarios of every test but the work count's share one session, as the
scenarios of the helper's users do.
"""

from collections import Counter
from pathlib import Path

import pytest

from tests._scenario_session import ScenarioRun, ScenarioSession

SCENARIOS = {
    "test_passes_twice_and_errors_at_a_teardown": """
        import pytest


        @pytest.fixture
        def raises_at_teardown():
            yield
            raise RuntimeError("the fixture's teardown raised")


        def test_passes_and_its_fixture_raises_at_teardown(raises_at_teardown):
            pass


        def test_passes():
            pass
        """,
    "test_fails_once": """
        def test_fails():
            assert False
        """,
    "test_raises_at_import": """
        raise RuntimeError("the module raised at import")
        """,
    "test_runs_beside_a_module_that_raises_at_import": """
        def test_passes_beside_a_module_that_raised_at_import():
            pass
        """,
    "test_passes_on_its_rerun": """
        import pytest

        attempts = []


        @pytest.mark.flaky(reruns=1)
        def test_fails_its_first_attempt_only():
            attempts.append(len(attempts) + 1)
            assert len(attempts) == 2
        """,
    "imported_by_a_scenario": """
        HELPER_VALUE = "written beside the scenarios"


        def test_would_count_if_this_helper_were_collected():
            pass
        """,
    "test_imports_a_helper": """
        from imported_by_a_scenario import HELPER_VALUE


        def test_reads_the_helper():
            assert HELPER_VALUE == "written beside the scenarios"
        """,
}


@pytest.fixture(scope="module")
def scenarios() -> ScenarioSession:
    return ScenarioSession(SCENARIOS)


@pytest.fixture
def run(scenarios: ScenarioSession, pytester_importing_test_helpers: pytest.Pytester) -> ScenarioRun:
    return scenarios.run_in(pytester_importing_test_helpers)


def test_each_modules_outcomes_are_what_the_summary_counts_of_its_reports(run: ScenarioRun) -> None:
    """A test that passes its call and errors at teardown counts once in each, as it does in the summary."""
    assert run.outcomes("test_passes_twice_and_errors_at_a_teardown") == {"passed": 2, "errors": 1}
    assert run.outcomes("test_fails_once") == {"failed": 1}


def test_the_modules_outcomes_add_up_to_the_sessions_summary(run: ScenarioRun) -> None:
    """Warnings are left out: the summary counts them for the session, not for a module's reports."""
    totals: Counter[str] = Counter()
    for module in SCENARIOS:
        totals.update(run.outcomes(module))
    summary = {noun: count for noun, count in run.result.parseoutcomes().items() if noun != "warnings"}

    assert dict(totals) == summary


def test_a_module_that_raises_at_import_errors_and_the_session_still_runs_its_siblings(run: ScenarioRun) -> None:
    assert run.outcomes("test_raises_at_import") == {"errors": 1}
    assert run.outcomes("test_runs_beside_a_module_that_raises_at_import") == {"passed": 1}


def test_a_plugins_own_category_counts_under_its_name(run: ScenarioRun) -> None:
    """rerunfailures, of the dev extra, reports an attempt it runs again as a rerun."""
    assert run.outcomes("test_passes_on_its_rerun") == {"rerun": 1, "passed": 1}


def test_a_module_a_scenario_imports_is_written_beside_the_scenarios_but_not_collected(run: ScenarioRun) -> None:
    assert (run.session_dir / "imported_by_a_scenario.py").is_file()
    assert run.outcomes("imported_by_a_scenario") == {}
    assert run.outcomes("test_imports_a_helper") == {"passed": 1}


def test_the_session_collects_its_directory_whatever_testpaths_its_ini_names(
    pytester_importing_test_helpers: pytest.Pytester,
) -> None:
    """The e2e scenarios' session reads a copy of pyproject.toml, which names testpaths = ["tests"]."""
    pytester_importing_test_helpers.makeini("[pytest]\ntestpaths = elsewhere\n")
    pytester_importing_test_helpers.mkdir("elsewhere")
    session = ScenarioSession({"test_passes_beside_the_ini": "def test_passes():\n    pass\n"})

    run = session.run_in(pytester_importing_test_helpers)

    assert run.outcomes("test_passes_beside_the_ini") == {"passed": 1}


def test_a_second_run_in_returns_the_first_run_without_running_the_scenarios_again(
    pytester_importing_test_helpers: pytest.Pytester, tmp_path: Path
) -> None:
    runs_log = tmp_path / "runs.log"
    session = ScenarioSession(
        {
            "test_logs_its_run": f"""
            def test_appends_a_line_to_the_runs_log():
                with open({str(runs_log)!r}, "a", encoding="utf-8") as runs:
                    runs.write("ran\\n")
            """
        }
    )

    first = session.run_in(pytester_importing_test_helpers)
    second = session.run_in(pytester_importing_test_helpers)

    assert second is first
    assert runs_log.read_text(encoding="utf-8").splitlines() == ["ran"]
    assert first.session_dir == pytester_importing_test_helpers.path

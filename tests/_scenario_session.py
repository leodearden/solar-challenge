# SPDX-License-Identifier: AGPL-3.0-or-later
"""Several scenario modules run in one pytester subprocess session, and what its summary counts of each module.

Each pytester session costs about 4 s of CPU to start Python, pytest and its
conftest's imports, so the pins whose scenarios need no session apiece share one.

Usage::

    from tests._scenario_session import ScenarioSession

    SCENARIOS = {"test_fetches_a_tmy": FETCHES_A_TMY, "fetches_and_carries_on": FETCHES_AND_CARRIES_ON}


    @pytest.fixture(scope="module")
    def offline_scenarios() -> ScenarioSession:
        return ScenarioSession(SCENARIOS)


    def test_a_fast_test_that_fetches_a_tmy_fails(suite: pytest.Pytester, offline_scenarios: ScenarioSession) -> None:
        run = offline_scenarios.run_in(suite)

        assert run.outcomes("test_fetches_a_tmy") == {"failed": 1, "errors": 1}
"""

import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests._scenario_outcomes_plugin import read_outcomes_log, recording_arguments

_PARSEOUTCOMES_NOUNS = {"error": "errors"}


@dataclass(frozen=True)
class ScenarioRun:
    """A ScenarioSession's run: pytest's result, the directory the session ran in, and each report's module file and summary category."""

    result: pytest.RunResult
    session_dir: Path
    report_categories: tuple[tuple[str, str], ...]

    def outcomes(self, module: str) -> dict[str, int]:
        """Return what the summary counts of *module*'s reports, in RunResult.parseoutcomes' nouns, e.g. {"passed": 2, "errors": 1}; {} when it has none."""
        module_file = f"{module}.py"
        return dict(
            Counter(
                _PARSEOUTCOMES_NOUNS.get(category, category)
                for file, category in self.report_categories
                if file == module_file
            )
        )


class ScenarioSession:
    """Scenario modules, by module name, run in one pytester session the first time a test asks; a test module holds one in a module-scoped fixture.

    The session collects its directory, whatever testpaths an ini there names,
    so it collects only the test_*.py modules, in file-name order, and a
    scenario may import any other module written beside them. It runs on past a
    module that fails to collect. *pytest_args* are added to the session's
    arguments.
    """

    def __init__(self, modules: Mapping[str, str], *pytest_args: str) -> None:
        self._modules = dict(modules)
        self._pytest_args = pytest_args
        self._run: ScenarioRun | None = None

    def run_in(self, pytester: pytest.Pytester) -> ScenarioRun:
        """Return the run, running the scenarios in *pytester*'s directory if no test has yet; every later call returns that run."""
        if self._run is None:
            self._run = _run_scenarios(pytester, self._modules, self._pytest_args)
        return self._run


def _run_scenarios(pytester: pytest.Pytester, modules: Mapping[str, str], pytest_args: tuple[str, ...]) -> ScenarioRun:
    pytester.makepyfile(**modules)
    with tempfile.TemporaryDirectory(prefix="scenario-outcomes-") as log_dir:
        log = Path(log_dir) / "outcomes.jsonl"
        result = pytester.runpytest_subprocess(
            *recording_arguments(log), "--continue-on-collection-errors", *pytest_args, pytester.path
        )
        report_categories = read_outcomes_log(log)
    return ScenarioRun(result, pytester.path, report_categories)

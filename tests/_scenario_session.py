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

The module is also the plugin the session loads to record the category the
summary counts each report under.
"""

import json
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

_OUTCOMES_LOG_OPTION = "--scenario-outcomes-log"

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
            "-p",
            __name__,
            f"{_OUTCOMES_LOG_OPTION}={log}",
            "--continue-on-collection-errors",
            *pytest_args,
            pytester.path,
        )
        report_categories = _read_outcomes_log(log)
    return ScenarioRun(result, pytester.path, report_categories)


def _read_outcomes_log(log: Path) -> tuple[tuple[str, str], ...]:
    """Return the (module file, category) pairs *log* holds, in report order; none when the session wrote no log."""
    if not log.exists():
        return ()
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return tuple((record["module"], record["category"]) for record in records)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        _OUTCOMES_LOG_OPTION,
        help="append each report's module file and the category the summary counts it under to this JSON-lines file",
    )


def pytest_configure(config: pytest.Config) -> None:
    log = config.getoption(_OUTCOMES_LOG_OPTION)
    if log is not None:
        config.pluginmanager.register(_OutcomesRecorder(config, Path(log)))


class _OutcomesRecorder:
    """Appends each report's module file, and the category the terminal summary counts it under, to a JSON-lines log."""

    def __init__(self, config: pytest.Config, log: Path) -> None:
        self._config = config
        self._log = log

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Record a test report under the category pytest_report_teststatus gives it, as the summary does; plugins' own included."""
        category = self._config.hook.pytest_report_teststatus(report=report, config=self._config)[0]
        if category:
            self._record(report, category)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        """Record a collect report that failed as an error and one that skipped as skipped, as the summary does."""
        if report.failed:
            self._record(report, "error")
        elif report.skipped:
            self._record(report, "skipped")

    def _record(self, report: pytest.TestReport | pytest.CollectReport, category: str) -> None:
        with self._log.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"module": report.nodeid.partition("::")[0], "category": category}) + "\n")

# SPDX-License-Identifier: AGPL-3.0-or-later
"""The plugin a ScenarioSession's pytest session loads: it logs each report's module file and the category the summary counts it under.

Only that session loads it, through the arguments recording_arguments gives;
the process that started the session reads the log back with read_outcomes_log.

Usage::

    from tests._scenario_outcomes_plugin import read_outcomes_log, recording_arguments

    result = pytester.runpytest_subprocess(*recording_arguments(log), pytester.path)
    report_categories = read_outcomes_log(log)
"""

import json
from pathlib import Path

import pytest

_OUTCOMES_LOG_OPTION = "--scenario-outcomes-log"


def recording_arguments(log: Path) -> tuple[str, ...]:
    """Return the pytest arguments that load this plugin into a session and have it log to *log*."""
    return ("-p", __name__, f"{_OUTCOMES_LOG_OPTION}={log}")


def read_outcomes_log(log: Path) -> tuple[tuple[str, str], ...]:
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

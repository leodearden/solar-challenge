# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pytest plugin that writes a JSON report of the tests a session collected.

Load it with `-p solar_challenge_collection_report`, with this directory on
PYTHONPATH, and give it `--collection-report=PATH`. Without that option it
registers nothing.

The report is {"tests": [...], "skipped_collectors": [...]}:

- "tests" are session.items in order, after -m, -k and --deselect deselection,
  each {"node_id": ..., "path": ..., "parametrize_id": ...}. "path" is the
  test's file relative to the rootdir, as node ids are, in posix form, and
  "parametrize_id" is item.callspec.id, or null for a test that is not
  parametrised.
- "skipped_collectors" are the collectors pytest skipped at collection, in the
  order it reported them, each {"node_id": ..., "reason": ...}: a module that
  importorskips, or a directory whose conftest skips. "reason" is the skip's
  message, e.g. "Skipped: could not import 'x': No module named 'x'".

pytest writes the report even when collection stops on an error, so only the
run's exit code says whether collection succeeded.

A report describes one session. A session whose report path already holds a
report stops with a usage error rather than replace it, so a command that runs
pytest more than once fails instead of reporting its last session alone.
"""

import json
import os
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--collection-report",
        metavar="PATH",
        default=None,
        help="write a JSON report of the tests this session collects to PATH",
    )


def pytest_configure(config: pytest.Config) -> None:
    report_path = config.getoption("collection_report")
    if report_path is not None:
        config.pluginmanager.register(_CollectionReporter(Path(report_path)))


class _CollectionReporter:
    """Records each collector pytest skips, and writes the report to its path when the session's collection finishes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._skipped_collectors: list[dict[str, str]] = []

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.skipped:
            self._skipped_collectors.append({"node_id": report.nodeid, "reason": _skip_message(report)})

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        tests = [_reported_test(item, session.config.rootpath) for item in session.items]
        report = {"tests": tests, "skipped_collectors": self._skipped_collectors}
        try:
            with self._path.open("x", encoding="utf-8") as report_file:
                json.dump(report, report_file)
        except FileExistsError:
            raise pytest.UsageError(
                f"--collection-report={self._path} already holds an earlier session's report: the command "
                "runs more than one pytest session, and a report describes only one"
            ) from None


def _skip_message(report: pytest.CollectReport) -> str:
    """Return a skipped collect report's message, the last of the (path, lineno, message) pytest records for a skip."""
    longrepr = report.longrepr
    return longrepr[2] if isinstance(longrepr, tuple) else str(longrepr)


def _reported_test(item: pytest.Item, rootpath: Path) -> dict[str, str | None]:
    callspec = getattr(item, "callspec", None)
    return {
        "node_id": item.nodeid,
        "path": Path(os.path.relpath(item.path, rootpath)).as_posix(),
        "parametrize_id": None if callspec is None else callspec.id,
    }

# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pytest plugin that writes a JSON report of the tests a session collected.

Load it with `-p solar_challenge_collection_report`, with this directory on
PYTHONPATH, and give it `--collection-report=PATH`. Without that option it
registers nothing.

The report is {"tests": [{"node_id": ..., "path": ..., "parametrize_id": ...}, ...]}:

- "tests" are session.items in order, after -m, -k and --deselect deselection;
- "path" is the test's file relative to the rootdir, as node ids are, in posix form;
- "parametrize_id" is item.callspec.id, or null for a test that is not parametrised.

pytest writes the report even when collection stops on an error, so only the
run's exit code says whether collection succeeded.
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
    """Writes the report to its path when the session's collection finishes."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        tests = [_reported_test(item, session.config.rootpath) for item in session.items]
        self._path.write_text(json.dumps({"tests": tests}), encoding="utf-8")


def _reported_test(item: pytest.Item, rootpath: Path) -> dict[str, str | None]:
    callspec = getattr(item, "callspec", None)
    return {
        "node_id": item.nodeid,
        "path": Path(os.path.relpath(item.path, rootpath)).as_posix(),
        "parametrize_id": None if callspec is None else callspec.id,
    }

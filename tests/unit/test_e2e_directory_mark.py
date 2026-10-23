# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins that tests/e2e/conftest.py marks each test under its directory e2e, and no other test, so no e2e module writes the mark.

The session runs under copies of this project's pyproject.toml, tests/conftest.py
and, in e2e/, the e2e conftest. It names that directory explicitly, as the
offline lane's e2e job names tests/e2e, because the root conftest's
collect_ignore keeps the directory out of any other collection.
"""

from pathlib import Path

import pytest

pytest.importorskip("flask")

WRITTEN_WITHOUT_THE_E2E_MARK = """
    def test_carries_the_e2e_mark(request):
        assert request.node.get_closest_marker("e2e") is not None
    """

BESIDE_THE_E2E_DIRECTORY = """
    def test_carries_no_e2e_mark(request):
        assert request.node.get_closest_marker("e2e") is None
    """


def test_the_e2e_conftest_marks_e2e_each_test_under_its_directory_and_no_other(
    pytester_under_root_conftest: pytest.Pytester, project_root: Path, e2e_conftest: Path
) -> None:
    pytester_under_root_conftest.makepyprojecttoml((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    pytester_under_root_conftest.makepyfile(
        **{
            "e2e/conftest": e2e_conftest.read_text(encoding="utf-8"),
            "e2e/test_written_without_the_e2e_mark": WRITTEN_WITHOUT_THE_E2E_MARK,
            "test_beside_the_e2e_directory": BESIDE_THE_E2E_DIRECTORY,
        }
    )

    result = pytester_under_root_conftest.runpytest_subprocess(
        "-p", "no:cacheprovider", "e2e", "test_beside_the_e2e_directory.py"
    )

    result.assert_outcomes(passed=2)

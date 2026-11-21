# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pytest session of this project keeps its numbered temp dirs under the project's own temp root, not under the pytest-of-<user> root that every pytest run of the user shares."""

import sys
from pathlib import Path

import pytest

from tests._project_temp_root import project_temp_root

_RECORDS_ITS_BASETEMP = """
    def test_records_its_basetemp(tmp_path_factory, request):
        (request.config.rootpath / "basetemp.txt").write_text(str(tmp_path_factory.getbasetemp()))
"""


def _basetemp_of_a_session(pytester: pytest.Pytester) -> Path:
    """Return the basetemp of a pytest session run in *pytester*'s directory with no --basetemp, which runpytest_subprocess would pass."""
    pytester.makepyfile(_RECORDS_ITS_BASETEMP)

    result = pytester.run(sys.executable, "-m", "pytest", "-p", "no:cacheprovider", timeout=120)

    result.assert_outcomes(passed=1)
    return Path((pytester.path / "basetemp.txt").read_text())


def test_a_session_started_with_no_temp_root_named_keeps_its_temp_dirs_under_the_projects_own_root(
    pytester_under_root_conftest: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    monkeypatch.setenv("TMPDIR", str(temp_dir))
    monkeypatch.delenv("PYTEST_DEBUG_TEMPROOT", raising=False)

    basetemp = _basetemp_of_a_session(pytester_under_root_conftest)

    assert basetemp.is_relative_to(project_temp_root(temp_dir)), (
        f"a session started with no temp root named kept its temp dirs in {basetemp}, outside the project's own "
        f"root {project_temp_root(temp_dir)}, so its exit would delete the leftover dirs other runs keep in the root "
        "it shares with them"
    )


def test_a_session_started_with_a_temp_root_named_keeps_its_temp_dirs_there(
    pytester_under_root_conftest: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    monkeypatch.setenv("TMPDIR", str(temp_dir))
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", str(chosen))

    basetemp = _basetemp_of_a_session(pytester_under_root_conftest)

    assert basetemp.is_relative_to(chosen), (
        f"a session started with PYTEST_DEBUG_TEMPROOT={chosen} kept its temp dirs in {basetemp}: the root that a "
        "parent session or the caller named was overridden, so the child sessions a test starts would not share "
        "their parent's root"
    )

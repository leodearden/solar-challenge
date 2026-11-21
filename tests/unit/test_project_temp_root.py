# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pytest session of this project keeps its numbered temp dirs under the project's own temp root, a directory of the user's closed to other users, not under the pytest-of-<user> root that every pytest run of the user shares."""

import stat
import sys
from pathlib import Path

import pytest

from tests._project_temp_root import TEMP_ROOT_VARIABLE, project_temp_root

_RECORDS_ITS_BASETEMP = """
    def test_records_its_basetemp(tmp_path_factory, request):
        (request.config.rootpath / "basetemp.txt").write_text(str(tmp_path_factory.getbasetemp()))
"""


def _run_a_session(pytester: pytest.Pytester) -> pytest.RunResult:
    """Run a pytest session in *pytester*'s directory with no --basetemp, which runpytest_subprocess would pass, whose one test records its basetemp in basetemp.txt."""
    pytester.makepyfile(_RECORDS_ITS_BASETEMP)
    return pytester.run(sys.executable, "-m", "pytest", "-p", "no:cacheprovider", timeout=120)


def _basetemp_of_a_session(pytester: pytest.Pytester) -> Path:
    """Return the basetemp of a session _run_a_session runs in *pytester*'s directory."""
    result = _run_a_session(pytester)

    result.assert_outcomes(passed=1)
    return Path((pytester.path / "basetemp.txt").read_text())


@pytest.fixture
def sessions_temp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return the temp dir under the test's tmp_path that TMPDIR names for the sessions the test runs, so they write nowhere outside tmp_path."""
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    monkeypatch.setenv("TMPDIR", str(temp_dir))
    return temp_dir


def test_a_session_started_with_no_temp_root_named_keeps_its_temp_dirs_under_the_projects_own_root(
    pytester_under_root_conftest: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, sessions_temp_dir: Path
) -> None:
    monkeypatch.delenv(TEMP_ROOT_VARIABLE, raising=False)
    own_root = project_temp_root(sessions_temp_dir)

    basetemp = _basetemp_of_a_session(pytester_under_root_conftest)

    assert basetemp.is_relative_to(own_root), (
        f"a session started with no temp root named kept its temp dirs in {basetemp}, outside the project's own "
        f"root {own_root}, so its exit would delete the leftover dirs other runs keep in the root it shares with them"
    )


@pytest.mark.usefixtures("sessions_temp_dir")
def test_a_session_started_with_a_temp_root_named_keeps_its_temp_dirs_there(
    pytester_under_root_conftest: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    monkeypatch.setenv(TEMP_ROOT_VARIABLE, str(chosen))

    basetemp = _basetemp_of_a_session(pytester_under_root_conftest)

    assert basetemp.is_relative_to(chosen), (
        f"a session started with {TEMP_ROOT_VARIABLE}={chosen} kept its temp dirs in {basetemp}: the root that a "
        "parent session or the caller named was overridden, so the child sessions a test starts would not share "
        "their parent's root"
    )


def test_a_session_refuses_a_temp_root_that_is_a_symbolic_link(
    pytester_under_root_conftest: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    sessions_temp_dir: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(TEMP_ROOT_VARIABLE, raising=False)
    root = project_temp_root(sessions_temp_dir)
    link_target = tmp_path / "link-target"
    link_target.mkdir()
    root.symlink_to(link_target, target_is_directory=True)

    result = _run_a_session(pytester_under_root_conftest)

    output = f"{result.stdout.str()}\n{result.stderr.str()}"
    assert result.ret != pytest.ExitCode.OK and str(root) in output, (
        f"a session whose temp root {root} is a symbolic link to {link_target} ran, or stopped without naming that "
        f"root:\n{output}"
    )
    assert not any(link_target.iterdir()), (
        f"a session whose temp root {root} is a symbolic link made {sorted(link_target.iterdir())} in the link's "
        "target, which whoever made the link chose"
    )


def test_a_session_closes_its_temp_root_to_other_users(
    pytester_under_root_conftest: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, sessions_temp_dir: Path
) -> None:
    monkeypatch.delenv(TEMP_ROOT_VARIABLE, raising=False)
    root = project_temp_root(sessions_temp_dir)
    root.mkdir()
    root.chmod(0o777)

    _basetemp_of_a_session(pytester_under_root_conftest)

    mode = stat.S_IMODE(root.stat().st_mode)
    assert mode & 0o077 == 0, (
        f"a session left its temp root {root} at mode {mode:o}, so other users could swap the temp dirs pytest makes "
        "in it"
    )

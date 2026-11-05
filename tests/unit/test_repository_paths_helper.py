# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_repository_paths.py: REPOSITORY_ROOT is the checkout's resolved root, SCENARIOS_DIR is its committed scenarios directory, and the project_root fixture of tests/conftest.py returns REPOSITORY_ROOT."""

from pathlib import Path

from tests._repository_paths import REPOSITORY_ROOT, SCENARIOS_DIR


def test_scenarios_dir_is_the_scenarios_directory_under_the_project_root(project_root: Path) -> None:
    assert SCENARIOS_DIR == (project_root / "scenarios").resolve()


def test_scenarios_dir_finds_the_committed_scenarios_from_any_working_directory() -> None:
    assert SCENARIOS_DIR.is_absolute()
    assert SCENARIOS_DIR.is_dir(), f"no directory at {SCENARIOS_DIR}"
    assert any(SCENARIOS_DIR.glob("*.yaml")), f"no scenario file (*.yaml) in {SCENARIOS_DIR}"


def test_repository_root_is_the_resolved_root_of_the_checkout() -> None:
    pyproject = REPOSITORY_ROOT / "pyproject.toml"
    helper = REPOSITORY_ROOT / "tests" / "_repository_paths.py"

    assert REPOSITORY_ROOT.is_absolute(), f"{REPOSITORY_ROOT} is not an absolute path"
    assert REPOSITORY_ROOT == REPOSITORY_ROOT.resolve(), (
        f"{REPOSITORY_ROOT} is not resolved: it resolves to {REPOSITORY_ROOT.resolve()}"
    )
    assert pyproject.is_file(), f"no file at {pyproject}"
    assert helper.is_file(), f"no file at {helper}"


def test_the_project_root_fixture_is_the_repository_root(project_root: Path) -> None:
    assert project_root == REPOSITORY_ROOT, (
        f"the project_root fixture returned {project_root}, not REPOSITORY_ROOT, {REPOSITORY_ROOT}"
    )

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_repository_paths.py: REPOSITORY_ROOT is the checkout's resolved root, SCENARIOS_DIR is its committed scenarios directory, the project_root fixture of tests/conftest.py returns REPOSITORY_ROOT, and no other module of tests/ works out a directory above its own from its own __file__."""

import ast
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


def _is_a_path_of_the_modules_own_file(node: ast.expr) -> bool:
    """Whether node is a call given __file__ alone, as Path(__file__) and pathlib.Path(__file__) are, or that call's resolve()."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "resolve"
        and not node.args
        and not node.keywords
    ):
        node = node.func.value
    return (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "__file__"
    )


def _climbs_from_its_own_file(node: ast.Attribute) -> bool:
    """Whether node is the .parents, or the .parent.parent, of a path of its module's own file: a directory above the module's own."""
    if node.attr == "parents":
        return _is_a_path_of_the_modules_own_file(node.value)
    return (
        node.attr == "parent"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "parent"
        and _is_a_path_of_the_modules_own_file(node.value.value)
    )


def test_only_the_helper_works_out_a_directory_above_its_own_from_its_file() -> None:
    helper = "tests/_repository_paths.py"
    sites: list[tuple[str, str]] = []
    for path in sorted((REPOSITORY_ROOT / "tests").rglob("*.py")):
        module = path.relative_to(REPOSITORY_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        sites.extend(
            (module, f"{module}:{node.lineno}: {ast.unparse(node)}")
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and _climbs_from_its_own_file(node)
        )

    others = "\n".join(site for module, site in sites if module != helper)
    assert {module for module, _ in sites} == {helper}, (
        f"only {helper} may work out a directory above its own from its own __file__, and these sites do:\n"
        f"{others}\n"
        f"Build the path from REPOSITORY_ROOT or SCENARIOS_DIR, imported from {helper}, so the repository root is "
        "stated once; a test function may request the project_root fixture, which returns REPOSITORY_ROOT"
    )

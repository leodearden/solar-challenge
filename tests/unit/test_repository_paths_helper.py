# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_repository_paths.py: REPOSITORY_ROOT is the checkout's resolved root, SCENARIOS_DIR is its committed scenarios directory, the project_root fixture of tests/conftest.py returns REPOSITORY_ROOT, and no other module of tests/ works out a directory above its own from its own __file__."""

import ast
from pathlib import Path

import pytest

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
    """Whether node is a call given only __file__, as Path(__file__) is, or only another such call, as Path(os.path.abspath(__file__)) is, or the resolve(...) or absolute() of such a call."""
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute) and node.func.attr in {"resolve", "absolute"}:
        return _is_a_path_of_the_modules_own_file(node.func.value)
    if len(node.args) != 1:
        return False
    (argument,) = node.args
    if isinstance(argument, ast.Name):
        return argument.id == "__file__"
    return _is_a_path_of_the_modules_own_file(argument)


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


def _lines_climbing_from_the_modules_own_file(tree: ast.Module) -> list[int]:
    """The line of each expression in a module's tree that works out a directory above the module's own from its own __file__, in line order."""
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and _climbs_from_its_own_file(node)
    )


def test_only_the_helper_works_out_a_directory_above_its_own_from_its_file() -> None:
    helper = "tests/_repository_paths.py"
    sites: list[tuple[str, str]] = []
    for path in sorted((REPOSITORY_ROOT / "tests").rglob("*.py")):
        module = path.relative_to(REPOSITORY_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        lines = source.split("\n")
        sites.extend(
            (module, f"{module}:{lineno}: {lines[lineno - 1].strip()}")
            for lineno in _lines_climbing_from_the_modules_own_file(ast.parse(source, filename=str(path)))
        )

    others = "\n".join(site for module, site in sites if module != helper)
    assert {module for module, _ in sites} == {helper}, (
        f"only {helper} may work out a directory above its own from its own __file__, and these sites do:\n"
        f"{others}\n"
        f"Build the path from REPOSITORY_ROOT or SCENARIOS_DIR, imported from {helper}, so the repository root is "
        "stated once; a test function may request the project_root fixture, which returns REPOSITORY_ROOT"
    )


@pytest.mark.parametrize(
    "climb",
    [
        pytest.param("Path(__file__).parents[1]", id="parents"),
        pytest.param("pathlib.Path(__file__).parents[1]", id="pathlib-parents"),
        pytest.param("Path(__file__).resolve().parents[1]", id="resolved-parents"),
        pytest.param("Path(__file__).parent.parent", id="parent-of-parent"),
        pytest.param("Path(__file__).resolve().parent.parent", id="resolved-parent-of-parent"),
        pytest.param("Path(__file__).resolve(strict=True).parents[1]", id="strictly-resolved-parents"),
        pytest.param("Path(__file__).absolute().parents[1]", id="absolute-parents"),
        pytest.param("Path(os.path.abspath(__file__)).parents[1]", id="abspath-parents"),
        pytest.param("Path(os.path.realpath(__file__)).parents[1]", id="realpath-parents"),
    ],
)
def test_a_climb_from_the_modules_own_file_is_found_on_its_line(climb: str) -> None:
    tree = ast.parse(f"from pathlib import Path\n\nROOT = {climb}\n")

    assert _lines_climbing_from_the_modules_own_file(tree) == [3], f"{climb} is not found on its line, 3"


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("Path(__file__).resolve().parent", id="own-directory"),
        pytest.param("Path(solar_challenge.__file__).resolve().parents[1]", id="another-modules-file"),
    ],
)
def test_the_modules_own_directory_and_another_modules_file_are_not_climbs(path: str) -> None:
    tree = ast.parse(f"from pathlib import Path\n\nPATH = {path}\n")

    assert _lines_climbing_from_the_modules_own_file(tree) == [], f"{path} is found as a climb"

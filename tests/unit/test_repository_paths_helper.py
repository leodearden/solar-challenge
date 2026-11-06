# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_repository_paths.py: REPOSITORY_ROOT is the checkout's resolved root, SCENARIOS_DIR is its committed scenarios directory, the project_root fixture of tests/conftest.py returns REPOSITORY_ROOT, no other module of tests/ works out a directory above its own from its own __file__, and no module of tests/ calls a working-directory getter either."""

import ast
from collections.abc import Callable
from pathlib import Path

import pytest

from tests._repository_paths import REPOSITORY_ROOT, SCENARIOS_DIR

_REPOSITORY_PATHS_HELPER = "tests/_repository_paths.py"
_BUILD_FROM_THE_HELPER_ADVICE = (
    f"Build the path from REPOSITORY_ROOT or SCENARIOS_DIR, imported from {_REPOSITORY_PATHS_HELPER}, "
    "so the repository root is stated once"
)


def test_scenarios_dir_finds_the_committed_scenarios_from_any_working_directory() -> None:
    assert SCENARIOS_DIR.is_absolute()
    assert SCENARIOS_DIR.is_dir(), f"no directory at {SCENARIOS_DIR}"
    assert any(SCENARIOS_DIR.glob("*.yaml")), f"no scenario file (*.yaml) in {SCENARIOS_DIR}"


def test_repository_root_is_the_resolved_root_of_the_checkout() -> None:
    pyproject = REPOSITORY_ROOT / "pyproject.toml"
    helper = REPOSITORY_ROOT / _REPOSITORY_PATHS_HELPER

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


_WORKING_DIRECTORY_GETTERS = frozenset({"cwd", "getcwd", "getcwdb"})


def _calls_a_working_directory_getter(node: ast.Call) -> bool:
    """Whether node calls a function or method named cwd, getcwd or getcwdb, as Path.cwd(), os.getcwd(), os.getcwdb() and a bare getcwd() do."""
    function = node.func
    if isinstance(function, ast.Attribute):
        return function.attr in _WORKING_DIRECTORY_GETTERS
    return isinstance(function, ast.Name) and function.id in _WORKING_DIRECTORY_GETTERS


def _lines_calling_a_working_directory_getter(tree: ast.Module) -> list[int]:
    """The line of each call in a module's tree of a function or method named cwd, getcwd or getcwdb, in line order."""
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _calls_a_working_directory_getter(node)
    )


_Detector = Callable[[ast.Module], list[int]]
_SitesByDetector = dict[_Detector, list[tuple[str, str]]]

_GATE_DETECTORS: tuple[_Detector, ...] = (
    _lines_climbing_from_the_modules_own_file,
    _lines_calling_a_working_directory_getter,
)


@pytest.fixture(scope="module")
def sites_in_tests() -> _SitesByDetector:
    """The (module, site) of every line each of _GATE_DETECTORS finds in the syntax tree of a Python module under tests/, in sorted module order: a module is its path from the repository root, and its site reads module:line: source.

    Each module is read and parsed once, for every detector, and its tree is dropped at once: the trees of
    every module kept alive make the cyclic collector scan them again and again, which cancels what sharing
    the parse saves.
    """
    sites: _SitesByDetector = {detector: [] for detector in _GATE_DETECTORS}
    for path in sorted((REPOSITORY_ROOT / "tests").rglob("*.py")):
        module = path.relative_to(REPOSITORY_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        lines = source.split("\n")
        tree = ast.parse(source, filename=str(path))
        for detector in _GATE_DETECTORS:
            sites[detector].extend(
                (module, f"{module}:{lineno}: {lines[lineno - 1].strip()}") for lineno in detector(tree)
            )
    return sites


def test_only_the_helper_works_out_a_directory_above_its_own_from_its_file(sites_in_tests: _SitesByDetector) -> None:
    sites = sites_in_tests[_lines_climbing_from_the_modules_own_file]

    others = "\n".join(site for module, site in sites if module != _REPOSITORY_PATHS_HELPER)
    assert {module for module, _ in sites} == {_REPOSITORY_PATHS_HELPER}, (
        f"only {_REPOSITORY_PATHS_HELPER} may work out a directory above its own from its own __file__, and these "
        f"sites do:\n{others}\n"
        f"{_BUILD_FROM_THE_HELPER_ADVICE}; a test function may request the project_root fixture, which returns "
        "REPOSITORY_ROOT"
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


def test_no_module_of_tests_calls_a_working_directory_getter(sites_in_tests: _SitesByDetector) -> None:
    sites = sites_in_tests[_lines_calling_a_working_directory_getter]

    listed = "\n".join(site for _, site in sites)
    assert sites == [], (
        "no module of tests/ may call Path.cwd, os.getcwd or os.getcwdb, since the working directory need not be "
        f"the repository root, and these sites do:\n{listed}\n"
        f"{_BUILD_FROM_THE_HELPER_ADVICE}; a test that needs a working directory of its own sets it with "
        "monkeypatch.chdir(tmp_path)"
    )


@pytest.mark.parametrize(
    "call",
    [
        pytest.param("Path.cwd()", id="path-cwd"),
        pytest.param("pathlib.Path.cwd()", id="pathlib-path-cwd"),
        pytest.param("os.getcwd()", id="os-getcwd"),
        pytest.param("getcwd()", id="bare-getcwd"),
        pytest.param("os.getcwdb()", id="os-getcwdb"),
    ],
)
def test_a_call_of_a_working_directory_getter_is_found_on_its_line(call: str) -> None:
    tree = ast.parse(f"import os\nfrom pathlib import Path\n\nHERE = {call}\n")

    assert _lines_calling_a_working_directory_getter(tree) == [4], f"{call} is not found on its line, 4"


@pytest.mark.parametrize(
    "setting",
    [
        pytest.param("monkeypatch.chdir(tmp_path)", id="monkeypatch-chdir"),
        pytest.param("subprocess.run(['ls'], cwd=REPOSITORY_ROOT)", id="cwd-argument"),
    ],
)
def test_setting_the_working_directory_is_not_a_call_of_a_getter(setting: str) -> None:
    tree = ast.parse(f"import subprocess\n\n{setting}\n")

    assert _lines_calling_a_working_directory_getter(tree) == [], f"{setting} is found as a getter call"

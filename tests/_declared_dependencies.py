# SPDX-License-Identifier: AGPL-3.0-or-later
"""The declared-dependency contract: what each source scope may import, and the files that import beyond it.

Every third-party import a source file requires must be satisfied by a
dependency declared for the run that loads that file, not by whatever another
requirement happens to pull in. A SourceScope pairs a selector of source files
with the extras, beside [project].dependencies, of the run that loads them;
each selector's docstring names that run. solar_challenge and tests are
first-party. An import inside a try block that handles ImportError is optional
by construction and exempt; dead_import_guards finds each such guard over
declared distributions only, whose handler can never run. Imports map to
distributions only through installed metadata, so a scope's check skips where
its extras are not installed.

Usage::

    from tests._declared_dependencies import (
        PACKAGE_SCOPES,
        SOURCE_SCOPES,
        SourceScope,
        assert_imports_only_declared,
        dead_import_guards,
        declared_distributions_or_skip,
    )

    @pytest.mark.parametrize("scope", SOURCE_SCOPES, ids=lambda scope: scope.name)
    def test_sources_import_only_declared_dependencies(project_root: Path, scope: SourceScope) -> None:
        assert_imports_only_declared(project_root, scope)

    for scope in PACKAGE_SCOPES:
        declared = declared_distributions_or_skip(project_root, scope.extras)
        dead = dead_import_guards(scope.select(project_root), declared)
"""

import ast
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution, packages_distributions
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tests._pyproject import core_requirements, extra_requirements

_IMPORT_FAILURES = {"ImportError", "ModuleNotFoundError"}
_FIRST_PARTY = frozenset({"solar_challenge", "tests"})
DEV = "dev"
WEB = "web"
E2E = "e2e"


@dataclass(frozen=True)
class SourceScope:
    """Source files, and the extras beside [project].dependencies of the run that loads them.

    name identifies the scope, and each test run for it. select returns the
    scope's .py files of the project root it is given. extras names the
    [project.optional-dependencies] groups whose requirements those files may import.
    """

    name: str
    select: Callable[[Path], list[Path]]
    extras: tuple[str, ...]


def _uninstalled(requirements: Iterable[Requirement]) -> list[str]:
    """Return the sorted names of the applicable *requirements* whose distribution is not installed."""
    missing: list[str] = []
    for requirement in requirements:
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        try:
            distribution(requirement.name)
        except PackageNotFoundError:
            missing.append(requirement.name)
    return sorted(missing)


def declared_distributions_or_skip(project_root: Path, extras: tuple[str, ...]) -> set[str]:
    """Return the canonical names a source scope may import: [project].dependencies plus the
    requirements of *extras*.

    Skips the calling test unless every applicable requirement of *extras* is installed,
    since imports map to distributions only through installed metadata.
    """
    requirements_of_extras = extra_requirements(project_root, extras)
    uninstalled = _uninstalled(requirements_of_extras)
    if uninstalled:
        install_flags = "".join(f" --extra {extra}" for extra in dict.fromkeys((DEV, *extras)))
        pytest.skip(
            "imports can be mapped to distributions only where the extras this source scope may "
            f"use are installed; not installed: {uninstalled}. "
            f"Install them, e.g. with `uv run{install_flags} pytest`"
        )
    return {canonicalize_name(r.name) for r in [*core_requirements(project_root), *requirements_of_extras]}


def _python_files_outside(directory: Path, excluded: Path) -> list[Path]:
    """Return the .py files under *directory* that are not under its subdirectory *excluded*."""
    return [source for source in directory.rglob("*.py") if not source.is_relative_to(excluded)]


def _web_sources(project_root: Path) -> list[Path]:
    """Return the package's .py files inside its web subpackage, the one the web extra serves."""
    return list((project_root / "src" / "solar_challenge" / WEB).rglob("*.py"))


def _core_sources(project_root: Path) -> list[Path]:
    """Return the package's .py files outside its web subpackage, which an install of the package
    without extras runs.
    """
    package_dir = project_root / "src" / "solar_challenge"
    return _python_files_outside(package_dir, package_dir / WEB)


def _script_sources(project_root: Path) -> list[Path]:
    """Return the .py files of scripts/, which run with the dev extra."""
    return list((project_root / "scripts").rglob("*.py"))


_DEV_ONLY_LANE_SUITES = (
    "tests/interpreter_matrix",
    "tests/integration/test_pvgis.py",
    "tests/css_build",
    "tests/newest_releases",
)
_LOADED_ABOVE_A_SUITE = frozenset({"__init__.py", "conftest.py"})


def _dev_only_lane_test_sources(project_root: Path) -> list[Path]:
    """Return the .py files of the suites in _DEV_ONLY_LANE_SUITES, which the offline lane's jobs
    that install the dev extra alone run, and the conftest.py and __init__.py files pytest loads
    above them.
    """
    missing = [suite for suite in _DEV_ONLY_LANE_SUITES if not (project_root / suite).exists()]
    assert not missing, (
        f"the dev-only lane suites {missing} do not exist; _DEV_ONLY_LANE_SUITES must name the suite "
        "of each offline-lane job that installs the dev extra alone"
    )
    suites = [project_root / suite for suite in _DEV_ONLY_LANE_SUITES]
    return [
        source
        for source in (project_root / "tests").rglob("*.py")
        if any(
            source.is_relative_to(suite)
            or (source.name in _LOADED_ABOVE_A_SUITE and suite.is_relative_to(source.parent))
            for suite in suites
        )
    ]


def _verify_test_sources(project_root: Path) -> list[Path]:
    """Return the .py files of tests/ outside tests/e2e that _dev_only_lane_test_sources does not
    select: the per-task verify's test_command runs them, installing the dev and web extras.
    """
    tests_dir = project_root / "tests"
    dev_only_lane_sources = set(_dev_only_lane_test_sources(project_root))
    return [
        source
        for source in _python_files_outside(tests_dir, tests_dir / "e2e")
        if source not in dev_only_lane_sources
    ]


def _e2e_test_sources(project_root: Path) -> list[Path]:
    """Return the .py files of tests/e2e: what the offline lane's e2e job runs, installing the
    dev, web and e2e extras.
    """
    return list((project_root / "tests" / "e2e").rglob("*.py"))


PACKAGE_SCOPES: tuple[SourceScope, ...] = (
    SourceScope("outside-web", _core_sources, ()),
    SourceScope("web", _web_sources, (WEB,)),
)
SOURCE_SCOPES: tuple[SourceScope, ...] = (
    *PACKAGE_SCOPES,
    SourceScope("scripts", _script_sources, (DEV,)),
    SourceScope("tests-dev-only-lanes", _dev_only_lane_test_sources, (DEV,)),
    SourceScope("tests-verify", _verify_test_sources, (DEV, WEB)),
    SourceScope("tests-e2e", _e2e_test_sources, (DEV, WEB, E2E)),
)


def _parse(source: Path) -> ast.Module:
    """Return the syntax tree of the Python *source* file."""
    return ast.parse(source.read_text(encoding="utf-8"), filename=str(source))


def _handles_import_failure(node: ast.Try) -> bool:
    """Return whether one of *node*'s handlers names ImportError or ModuleNotFoundError."""
    return any(
        isinstance(name, ast.Name) and name.id in _IMPORT_FAILURES
        for handler in node.handlers
        if handler.type is not None
        for name in ast.walk(handler.type)
    )


def _required_imports(nodes: Iterable[ast.AST]) -> Iterator[ast.Import | ast.ImportFrom]:
    """Yield the imports under *nodes*, skipping the body of every try that handles ImportError."""
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, ast.Try) and _handles_import_failure(node):
            yield from _required_imports([*node.handlers, *node.orelse, *node.finalbody])
        else:
            yield from _required_imports(ast.iter_child_nodes(node))


def _top_level_modules(imports: Iterable[ast.Import | ast.ImportFrom]) -> set[str]:
    """Return the top-level module of every absolute import among *imports*."""
    modules: set[str] = set()
    for node in imports:
        if isinstance(node, ast.Import):
            modules.update(alias.name.partition(".")[0] for alias in node.names)
        elif node.level == 0 and node.module:
            modules.add(node.module.partition(".")[0])
    return modules


def _required_top_level_modules(sources: Iterable[Path]) -> set[str]:
    """Return the top-level module of every required absolute import in *sources*.

    Function-local and TYPE_CHECKING imports count; relative imports and
    ImportError-guarded imports do not.
    """
    modules: set[str] = set()
    for source in sources:
        modules |= _top_level_modules(_required_imports([_parse(source)]))
    return modules


def _third_party_modules(modules: set[str]) -> set[str]:
    """Return *modules* without the standard library and the first-party solar_challenge and
    tests packages.
    """
    return modules - sys.stdlib_module_names - _FIRST_PARTY


def _third_party_distributions(source: Path, providers: Mapping[str, list[str]]) -> set[str]:
    """Return the canonical names of the distributions that provide the third-party modules
    *source* requires, as *providers* maps modules to distributions.

    Standard-library modules and the first-party solar_challenge and tests packages are dropped.
    """
    third_party = _third_party_modules(_required_top_level_modules([source]))
    unprovided = sorted(module for module in third_party if module not in providers)
    assert not unprovided, (
        f"no installed distribution provides the modules {source} imports: {unprovided}; "
        "declare and install the distribution that provides them"
    )
    return {canonicalize_name(dist) for module in third_party for dist in providers[module]}


def undeclared_distributions(
    sources: Iterable[Path],
    declared: set[str],
) -> list[tuple[Path, list[str]]]:
    """Return (file, undeclared distributions) for every file in *sources* that requires a
    third-party distribution outside *declared*.
    """
    providers = packages_distributions()
    undeclared: list[tuple[Path, list[str]]] = []
    for source in sources:
        distributions = sorted(_third_party_distributions(source, providers) - declared)
        if distributions:
            undeclared.append((source, distributions))
    return sorted(undeclared)


def _import_guards(sources: Iterable[Path]) -> Iterator[tuple[Path, ast.Try]]:
    """Yield every try block in *sources* that handles ImportError, with the file it is in."""
    for source in sources:
        for node in ast.walk(_parse(source)):
            if isinstance(node, ast.Try) and _handles_import_failure(node):
                yield source, node


def _guarded_imports(guard: ast.Try) -> Iterator[ast.Import | ast.ImportFrom]:
    """Yield the imports in *guard*'s body, the only part of a try its handlers guard."""
    for statement in guard.body:
        for node in ast.walk(statement):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                yield node


def dead_import_guards(
    sources: Iterable[Path],
    declared: set[str],
) -> list[tuple[Path, int, list[str]]]:
    """Return (file, line, guarded modules) for every ImportError guard whose guarded
    third-party imports are all provided by *declared* distributions.

    A guard over no third-party import is not judged.
    """
    providers = packages_distributions()
    dead: list[tuple[Path, int, list[str]]] = []
    for source, guard in _import_guards(sources):
        guarded = _third_party_modules(_top_level_modules(_guarded_imports(guard)))
        if guarded and all(
            any(canonicalize_name(dist) in declared for dist in providers.get(module, ()))
            for module in guarded
        ):
            dead.append((source, guard.lineno, sorted(guarded)))
    return sorted(dead)


def assert_imports_only_declared(project_root: Path, scope: SourceScope) -> None:
    """Assert that every third-party distribution *scope*'s files of *project_root* require is declared for it.

    The failure names each offending file, relative to *project_root*, with the undeclared
    distributions it requires, and the groups of pyproject.toml the scope may import from.
    Skips the calling test as declared_distributions_or_skip does.
    """
    declared = declared_distributions_or_skip(project_root, scope.extras)
    sources = scope.select(project_root)
    undeclared = [
        f"{source.relative_to(project_root)} requires {distributions}"
        for source, distributions in undeclared_distributions(sources, declared)
    ]
    groups = ", ".join(
        ["[project].dependencies", *(f"[project.optional-dependencies].{extra}" for extra in scope.extras)]
    )
    assert not undeclared, (
        f"these files require distributions missing from {groups}: {undeclared}. "
        "Declare them in one of those groups in pyproject.toml, or make the import optional "
        "inside a try block that handles ImportError"
    )

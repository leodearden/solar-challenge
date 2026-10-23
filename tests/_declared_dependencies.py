# SPDX-License-Identifier: AGPL-3.0-or-later
"""The declared-dependency contract: what each source scope may import, and the files that import beyond it.

Every third-party import a source file requires must be satisfied by a
dependency declared for the run that loads that file, not by whatever another
requirement happens to pull in. A SourceScope pairs a selector of source files
with the extras, beside [project].dependencies, of the run that loads them;
each selector's docstring names that run. solar_challenge and tests are
first-party. A module a file names to pytest.importorskip as a string literal
counts as an import it requires, since the test skips wherever that module is
missing. An import inside a try block that handles ImportError is optional
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
from importlib.machinery import PathFinder
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


def _dev_only_lane_suite_files(project_root: Path) -> list[Path]:
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


def _dev_only_lane_test_sources(project_root: Path) -> list[Path]:
    """Return the files of _dev_only_lane_suite_files and every module of the tests package they
    import, transitively. A pytest_plugins entry and a module named to pytest.importorskip each
    count as an absolute import.

    Each of those modules runs in an offline-lane job that installs the dev extra alone, so a
    helper the verify also imports is judged here, against the dev extra alone, not with the
    verify's web extra.
    """
    return _with_the_tests_modules_they_import(project_root, _dev_only_lane_suite_files(project_root))


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


def _pytest_plugins_values(tree: ast.Module) -> Iterator[ast.expr]:
    """Yield the value of each module-level assignment of pytest_plugins in *tree*, annotated or not.

    An annotation with no value assigns nothing.
    """
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets, value = statement.targets, statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets, value = [statement.target], statement.value
        else:
            continue
        if any(isinstance(target, ast.Name) and target.id == "pytest_plugins" for target in targets):
            yield value


def _pytest_plugins(source: Path, tree: ast.Module) -> list[str]:
    """Return the plugin names of the module-level pytest_plugins assignments in *tree*, the
    syntax tree of *source*.

    pytest imports each when it loads a conftest, test module or plugin that sets one. pytest
    accepts any expression, but the names are read without running *source*, so the value must
    be a literal: a str, split at commas as pytest splits it, or a sequence of str. Any other
    value fails, naming *source*, the line and the expression.
    """
    names: list[str] = []
    for value in _pytest_plugins_values(tree):
        try:
            plugins = ast.literal_eval(value)
        except ValueError:
            raise AssertionError(
                f"{source}:{value.lineno} sets pytest_plugins to {ast.unparse(value)}, which is not a "
                "literal; write pytest_plugins as a literal list or tuple of module names, or as a "
                "comma-separated string, for the declared-dependency contract to follow the plugins it names"
            ) from None
        names.extend(plugins.split(",") if isinstance(plugins, str) else plugins)
    return names


def _calls_importorskip(call: ast.Call) -> bool:
    """Return whether *call* calls importorskip: as the attribute of a module, such as
    pytest.importorskip, or by the bare name imported from pytest.
    """
    callee = call.func
    if isinstance(callee, ast.Attribute):
        return callee.attr == "importorskip"
    return isinstance(callee, ast.Name) and callee.id == "importorskip"


def _importorskip_modnames(tree: ast.AST) -> Iterator[str]:
    """Yield the module name each importorskip call in *tree* passes as a string literal,
    positionally or as modname=, wherever the call is.

    The call imports the module or skips its test, and an ImportError handler around it cannot
    catch the skip, so the file requires the module wherever the call is. A modname that is not
    a string literal is not read.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _calls_importorskip(node):
            keyword_modnames = [keyword.value for keyword in node.keywords if keyword.arg == "modname"]
            for modname in [*node.args[:1], *keyword_modnames]:
                if isinstance(modname, ast.Constant) and isinstance(modname.value, str):
                    yield modname.value


def _directory_of_from_import(project_root: Path, source: Path, node: ast.ImportFrom) -> Path:
    """Return the directory the from-import *node* of *source* resolves from: *project_root* for
    an absolute import, else *source*'s package directory, climbed level - 1 times.

    A level that climbs out of *project_root*, even to above the filesystem root, fails naming
    *source*, the line and the import: Python rejects a relative import beyond its top-level
    package.
    """
    if not node.level:
        return project_root
    directory = source.parents[: node.level][-1]
    assert directory.is_relative_to(project_root), (
        f"{source}:{node.lineno} imports `{ast.unparse(node)}`, which climbs out of {project_root}; "
        "a relative import cannot leave its top-level package"
    )
    return directory


def _import_targets(project_root: Path, source: Path) -> Iterator[tuple[Path, list[str]]]:
    """Yield (directory, dotted-name parts) for each module *source* may import.

    An absolute name resolves from *project_root* and a relative one from *source*'s package
    directory. Imports count as _required_imports counts them, and each pytest_plugins entry
    and each module named to pytest.importorskip counts as an absolute import. The last part of
    a from-import's name may be an attribute of the module before it, not a module.

    A relative import that climbs out of *project_root*, or a pytest_plugins value that is no
    literal, fails naming *source* and the line.
    """
    tree = _parse(source)
    for node in _required_imports([tree]):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield project_root, alias.name.split(".")
        else:
            directory = _directory_of_from_import(project_root, source, node)
            module_parts = node.module.split(".") if node.module else []
            for alias in node.names:
                yield directory, [*module_parts, alias.name]
    for name in [*_pytest_plugins(source, tree), *_importorskip_modnames(tree)]:
        yield project_root, name.split(".")


def _files_run_by_importing(directory: Path, parts: list[str]) -> list[Path]:
    """Return the files that importing the dotted name *parts* from *directory* runs: each
    package's __init__.py down to the module's own file.

    The walk stops at a part that is not found or that follows a plain module, so a trailing
    attribute adds nothing. Nothing is imported.
    """
    files: list[Path] = []
    search_path = [str(directory)]
    for depth in range(1, len(parts) + 1):
        spec = PathFinder.find_spec(".".join(parts[:depth]), search_path)
        if spec is None:
            break
        if spec.origin is not None:
            files.append(Path(spec.origin))
        if spec.submodule_search_locations is None:
            break
        search_path = list(spec.submodule_search_locations)
    return files


def _with_the_tests_modules_they_import(project_root: Path, sources: list[Path]) -> list[Path]:
    """Return *sources* and every module of the tests package that they import, transitively."""
    tests_dir = project_root / "tests"
    selected = dict.fromkeys(sources)
    pending = list(sources)
    while pending:
        source = pending.pop()
        reached = (
            module_file
            for directory, parts in _import_targets(project_root, source)
            for module_file in _files_run_by_importing(directory, parts)
        )
        for module_file in reached:
            if module_file.is_relative_to(tests_dir) and module_file not in selected:
                selected[module_file] = None
                pending.append(module_file)
    return list(selected)


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
    """Return the top-level module of every required absolute import in *sources*, and of every
    module they name to pytest.importorskip.

    Function-local and TYPE_CHECKING imports count; relative imports and
    ImportError-guarded imports do not.
    """
    modules: set[str] = set()
    for source in sources:
        tree = _parse(source)
        modules |= _top_level_modules(_required_imports([tree]))
        modules |= {name.partition(".")[0] for name in _importorskip_modnames(tree)}
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
        f"no installed distribution provides the modules {source} requires: {unprovided}; "
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
        "A module a file names to pytest.importorskip counts as required, since its test skips "
        "wherever the module is missing. Declare them in one of those groups in pyproject.toml, "
        "or, in src/solar_challenge, make the import optional inside a try block that handles "
        "ImportError"
    )

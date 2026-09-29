# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dependency declaration contract tests.

Every third-party import the package requires must be satisfied by a declared
dependency, not by whatever another package's extra happens to pull in: code
outside the web subpackage needs DIRECT core dependencies, and the web
subpackage needs core dependencies or the `web` extra that serves it.  No core
dependency may request an extra its distribution does not provide.  No declared
requirement may carry an environment marker that holds only on Python minors
requires-python does not admit, since it could never install.  An import
inside a try block that handles ImportError is optional by construction and
exempt.  pyproject.toml is parsed structurally (TOML plus PEP 508
requirements), not by regex.

pyproject.toml is also the only dependency declaration: no requirements*.txt at
the project root may restate it, since a hand-maintained copy drifts from it.
"""

import ast
import sys
from collections.abc import Callable, Iterable, Iterator
from importlib.metadata import PackageNotFoundError, distribution, metadata, packages_distributions
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tests._interpreters import (
    admitted_minor_versions,
    minor_versions_where_marker_holds,
    requires_python,
)
from tests._pyproject import load_project_table

_IMPORT_FAILURES = {"ImportError", "ModuleNotFoundError"}
_WEB = "web"


def _core_requirements(project_root: Path) -> list[Requirement]:
    """Return the parsed [project].dependencies of pyproject.toml."""
    return [Requirement(specifier) for specifier in load_project_table(project_root)["dependencies"]]


def _extra_requirements(project_root: Path, extras: Iterable[str]) -> list[Requirement]:
    """Return the parsed [project.optional-dependencies] requirements of each named extra."""
    optional = load_project_table(project_root)["optional-dependencies"]
    return [Requirement(specifier) for extra in extras for specifier in optional[extra]]


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


def _web_sources(package_dir: Path) -> list[Path]:
    """Return the package's .py files inside its web subpackage, the one the web extra serves."""
    return list((package_dir / _WEB).rglob("*.py"))


def _core_sources(package_dir: Path) -> list[Path]:
    """Return the package's .py files outside its web subpackage."""
    web_sources = set(_web_sources(package_dir))
    return [source for source in package_dir.rglob("*.py") if source not in web_sources]


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


def _required_top_level_modules(sources: Iterable[Path]) -> set[str]:
    """Return the top-level module of every required absolute import in *sources*.

    Function-local and TYPE_CHECKING imports count; relative imports and
    ImportError-guarded imports do not.
    """
    modules: set[str] = set()
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in _required_imports([tree]):
            if isinstance(node, ast.Import):
                modules.update(alias.name.partition(".")[0] for alias in node.names)
            elif node.level == 0 and node.module:
                modules.add(node.module.partition(".")[0])
    return modules


def _third_party_distributions(modules: set[str]) -> set[str]:
    """Return the canonical names of the installed distributions providing *modules*.

    Standard-library modules and the first-party solar_challenge package are dropped.
    """
    third_party = modules - sys.stdlib_module_names - {"solar_challenge"}
    providers = packages_distributions()
    unprovided = sorted(module for module in third_party if module not in providers)
    assert not unprovided, (
        f"no installed distribution provides the imported modules {unprovided}; "
        "declare and install the distribution that provides them"
    )
    return {canonicalize_name(dist) for module in third_party for dist in providers[module]}


@pytest.mark.parametrize(
    ("select_sources", "extras"),
    [
        pytest.param(_core_sources, (), id="outside-web"),
        pytest.param(_web_sources, (_WEB,), id="web"),
    ],
)
def test_sources_import_only_declared_dependencies(
    project_root: Path,
    select_sources: Callable[[Path], list[Path]],
    extras: tuple[str, ...],
) -> None:
    """Every third-party distribution a source scope requires must be declared for that scope."""
    extra_requirements = _extra_requirements(project_root, extras)
    uninstalled = _uninstalled(extra_requirements)
    if uninstalled:
        install_flags = "".join(f" --extra {extra}" for extra in extras)
        pytest.skip(
            "imports can be mapped to distributions only where the extras this source scope may "
            f"use are installed; not installed: {uninstalled}. "
            f"Install them, e.g. with `uv run --extra dev{install_flags} pytest`"
        )
    required = _third_party_distributions(
        _required_top_level_modules(select_sources(project_root / "src" / "solar_challenge"))
    )
    allowed = [*_core_requirements(project_root), *extra_requirements]
    declared = {canonicalize_name(r.name) for r in allowed}

    undeclared = sorted(required - declared)
    groups = ", ".join(
        ["[project].dependencies", *(f"[project.optional-dependencies].{extra}" for extra in extras)]
    )
    assert not undeclared, (
        f"this source scope of src/solar_challenge requires distributions missing from {groups}; "
        f"undeclared: {undeclared}; required={sorted(required)}. "
        "Declare them in one of those groups in pyproject.toml, or make the import optional "
        "inside a try block that handles ImportError"
    )


def test_core_dependencies_request_only_provided_extras(project_root: Path) -> None:
    """No core dependency may request an extra that its installed distribution does not provide."""
    unknown_extras: dict[str, list[str]] = {}
    for requirement in _core_requirements(project_root):
        if not requirement.extras:
            continue
        provides_extra = metadata(requirement.name).get_all("Provides-Extra") or []
        provided = {canonicalize_name(extra) for extra in provides_extra}
        missing = {canonicalize_name(extra) for extra in requirement.extras} - provided
        if missing:
            unknown_extras[requirement.name] = sorted(missing)

    assert not unknown_extras, (
        f"unknown extras: {unknown_extras} — [project].dependencies requests extras the "
        "installed distributions do not provide. Resolvers (uv, pip) warn about unknown "
        "extras in every consumer's lock or install; drop the extra and depend directly on "
        "what the code needs"
    )


def test_dependency_markers_hold_on_some_admitted_interpreter(project_root: Path) -> None:
    """No declared requirement may be gated to Python minors that requires-python does not admit.

    A marker that holds on no candidate minor on this host (e.g. another OS's
    sys_platform) is not version-gated here and is not judged.
    """
    extras = load_project_table(project_root)["optional-dependencies"].keys()
    requirements = [*_core_requirements(project_root), *_extra_requirements(project_root, extras)]
    python_range = requires_python(project_root)
    admitted = admitted_minor_versions(python_range)

    dead: list[str] = []
    for requirement in requirements:
        if requirement.marker is None:
            continue
        holds_on = minor_versions_where_marker_holds(requirement.marker)
        if holds_on and holds_on.isdisjoint(admitted):
            dead.append(str(requirement))

    assert not dead, (
        f"declared requirements {dead} can never install on an interpreter "
        f"requires-python={str(python_range)!r} admits: each marker holds only on Python "
        "minors outside that range. Delete them from pyproject.toml"
    )


def test_no_requirements_file_duplicates_pyproject(project_root: Path) -> None:
    """pyproject.toml must be the only dependency declaration; no requirements*.txt may restate it."""
    duplicates = sorted(path.name for path in project_root.glob("requirements*.txt"))
    assert not duplicates, (
        f"{duplicates} at the project root restate the dependencies pyproject.toml declares, "
        "and a hand-maintained copy drifts from its source; delete them and install from "
        'pyproject.toml instead (pip install -e ".[dev]", or uv run --extra dev)'
    )

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dependency declaration contract tests.

Every third-party import the package requires outside its web subpackage
(which the `web` extra serves) must be satisfied by a DIRECT core dependency,
not by whatever another package's extra happens to pull in, and no core
dependency may request an extra its distribution does not provide.  An import
inside a try block that handles ImportError is optional by construction and
exempt.  pyproject.toml is parsed structurally (TOML plus PEP 508
requirements), not by regex.
"""

import ast
import sys
from collections.abc import Iterable, Iterator
from importlib.metadata import metadata, packages_distributions
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tests._pyproject import load_project_table

_IMPORT_FAILURES = {"ImportError", "ModuleNotFoundError"}


def _core_requirements(project_root: Path) -> list[Requirement]:
    """Return the parsed [project].dependencies of pyproject.toml."""
    return [Requirement(s) for s in load_project_table(project_root)["dependencies"]]


def _core_sources(package_dir: Path) -> list[Path]:
    """Return the package's .py files outside its web subpackage."""
    web_dir = package_dir / "web"
    return [source for source in package_dir.rglob("*.py") if web_dir not in source.parents]


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


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="before Python 3.11, importlib.metadata.packages_distributions() reads only "
    "top_level.txt, which wheels such as numpy, pandas, rich and typer do not ship",
)
def test_core_sources_import_only_declared_core_dependencies(project_root: Path) -> None:
    """Every third-party distribution the package requires outside web/ must be a declared core dependency."""
    required = _third_party_distributions(
        _required_top_level_modules(_core_sources(project_root / "src" / "solar_challenge"))
    )
    declared = {canonicalize_name(r.name) for r in _core_requirements(project_root)}

    undeclared = sorted(required - declared)
    assert not undeclared, (
        f"src/solar_challenge (outside web/) requires distributions missing from "
        f"[project].dependencies; undeclared: {undeclared}; required={sorted(required)}. "
        "Add them to [project].dependencies in pyproject.toml, or make the import optional "
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

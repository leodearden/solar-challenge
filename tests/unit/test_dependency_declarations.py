# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dependency declaration contract tests.

The CLI's third-party imports must be satisfied by DIRECT core dependencies,
not by whatever another package's extra happens to pull in, and no core
dependency may request an extra its distribution does not provide.
pyproject.toml is parsed structurally (TOML plus PEP 508 requirements), not by
regex.
"""

import ast
import sys
from importlib.metadata import metadata, packages_distributions
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tests._pyproject import load_project_table


def _core_requirements(project_root: Path) -> list[Requirement]:
    """Return the parsed [project].dependencies of pyproject.toml."""
    return [Requirement(s) for s in load_project_table(project_root)["dependencies"]]


def _imported_top_level_modules(package_dir: Path) -> set[str]:
    """Return the top-level module of every absolute import in the .py files under *package_dir*.

    Function-local and TYPE_CHECKING imports count; relative imports are skipped.
    """
    modules: set[str] = set()
    for source in package_dir.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
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


def test_cli_third_party_imports_are_declared_core_dependencies(project_root: Path) -> None:
    """Every third-party distribution the CLI imports must be a declared core dependency."""
    imported = _third_party_distributions(
        _imported_top_level_modules(project_root / "src" / "solar_challenge" / "cli")
    )
    declared = {canonicalize_name(r.name) for r in _core_requirements(project_root)}

    undeclared = sorted(imported - declared)
    assert not undeclared, (
        f"src/solar_challenge/cli imports distributions missing from [project].dependencies; "
        f"undeclared: {undeclared}; imported={sorted(imported)}. "
        "Add them to [project].dependencies in pyproject.toml"
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

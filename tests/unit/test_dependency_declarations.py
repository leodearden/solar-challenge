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
exempt, but the guard must then guard a distribution its scope does not
declare: a declared distribution always imports in a valid install, so a
guard over declared distributions only is dead code.  pyproject.toml is parsed
structurally (TOML plus PEP 508 requirements), not by regex.

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


def _declared_distributions_or_skip(project_root: Path, extras: tuple[str, ...]) -> set[str]:
    """Return the canonical names a source scope may import: [project].dependencies plus the
    requirements of *extras*.

    Skips the calling test unless every applicable requirement of *extras* is installed,
    since imports map to distributions only through installed metadata.
    """
    extra_requirements = _extra_requirements(project_root, extras)
    uninstalled = _uninstalled(extra_requirements)
    if uninstalled:
        install_flags = "".join(f" --extra {extra}" for extra in extras)
        pytest.skip(
            "imports can be mapped to distributions only where the extras this source scope may "
            f"use are installed; not installed: {uninstalled}. "
            f"Install them, e.g. with `uv run --extra dev{install_flags} pytest`"
        )
    return {canonicalize_name(r.name) for r in [*_core_requirements(project_root), *extra_requirements]}


def _web_sources(package_dir: Path) -> list[Path]:
    """Return the package's .py files inside its web subpackage, the one the web extra serves."""
    return list((package_dir / _WEB).rglob("*.py"))


def _core_sources(package_dir: Path) -> list[Path]:
    """Return the package's .py files outside its web subpackage."""
    web_sources = set(_web_sources(package_dir))
    return [source for source in package_dir.rglob("*.py") if source not in web_sources]


_SOURCE_SCOPES = [
    pytest.param(_core_sources, (), id="outside-web"),
    pytest.param(_web_sources, (_WEB,), id="web"),
]


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
    """Return *modules* without the standard library and the first-party solar_challenge package."""
    return modules - sys.stdlib_module_names - {"solar_challenge"}


def _third_party_distributions(modules: set[str]) -> set[str]:
    """Return the canonical names of the installed distributions providing *modules*.

    Standard-library modules and the first-party solar_challenge package are dropped.
    """
    third_party = _third_party_modules(modules)
    providers = packages_distributions()
    unprovided = sorted(module for module in third_party if module not in providers)
    assert not unprovided, (
        f"no installed distribution provides the imported modules {unprovided}; "
        "declare and install the distribution that provides them"
    )
    return {canonicalize_name(dist) for module in third_party for dist in providers[module]}


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


def _dead_import_guards(
    sources: Iterable[Path],
    declared: set[str],
) -> list[tuple[Path, int, list[str]]]:
    """Return (file, line, guarded modules) for every ImportError guard whose guarded
    third-party imports are all provided by *declared* distributions.

    A guard over no third-party import, such as web/app.py's first-party blueprint
    guards, is not judged.
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


@pytest.mark.parametrize(("select_sources", "extras"), _SOURCE_SCOPES)
def test_sources_import_only_declared_dependencies(
    project_root: Path,
    select_sources: Callable[[Path], list[Path]],
    extras: tuple[str, ...],
) -> None:
    """Every third-party distribution a source scope requires must be declared for that scope."""
    declared = _declared_distributions_or_skip(project_root, extras)
    required = _third_party_distributions(
        _required_top_level_modules(select_sources(project_root / "src" / "solar_challenge"))
    )

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


@pytest.mark.parametrize(("select_sources", "extras"), _SOURCE_SCOPES)
def test_import_guards_guard_an_undeclared_dependency(
    project_root: Path,
    select_sources: Callable[[Path], list[Path]],
    extras: tuple[str, ...],
) -> None:
    """Every try that handles ImportError must guard a distribution its source scope does not declare.

    Its handler runs only if a guarded import fails, and a declared distribution always
    imports in a valid install, so a guard over declared distributions only is dead code.
    """
    declared = _declared_distributions_or_skip(project_root, extras)
    sources = select_sources(project_root / "src" / "solar_challenge")
    dead = [
        f"{source.relative_to(project_root)}:{line} guards {modules}"
        for source, line, modules in _dead_import_guards(sources, declared)
    ]
    assert not dead, (
        f"these ImportError guards are dead code: {dead}. Each guards only distributions its "
        "source scope declares, and a declared distribution always imports in a valid install, "
        "so the except branch can never run. Delete the guard and its fallback, or, if the "
        "import is meant to be optional, stop declaring the distribution"
    )


def _write_import_guard(path: Path, *body_lines: str) -> Path:
    """Write *path* as a module whose one function runs *body_lines* in a try that handles
    ImportError, and return *path*. The try is on line 2.
    """
    body = "".join(f"        {line}\n" for line in body_lines)
    path.write_text(
        f"def render():\n    try:\n{body}    except ImportError:\n        return None\n",
        encoding="utf-8",
    )
    return path


def test_dead_import_guards_flags_only_guards_wholly_over_declared_distributions(
    tmp_path: Path,
) -> None:
    """A guard is dead only when declared distributions provide every third-party module it guards.

    Once src/ holds no dead guard, test_import_guards_guard_an_undeclared_dependency passes
    for a detector that flags nothing, so this checks the detector on guards of known verdict.
    """
    unprovided = "no_installed_distribution_provides_this_module"
    dead_import = _write_import_guard(tmp_path / "dead_import.py", "import yaml")
    dead_nested_from_import = _write_import_guard(
        tmp_path / "dead_nested_from_import.py",
        "if sys.version_info >= (3, 11):",
        "    from yaml import safe_load",
    )
    live_unprovided = _write_import_guard(tmp_path / "live_unprovided.py", f"import {unprovided}")
    live_partly_declared = _write_import_guard(
        tmp_path / "live_partly_declared.py", "import yaml", f"import {unprovided}"
    )

    dead = _dead_import_guards(
        [dead_import, dead_nested_from_import, live_unprovided, live_partly_declared],
        declared={"pyyaml"},
    )

    assert dead == [(dead_import, 2, ["yaml"]), (dead_nested_from_import, 2, ["yaml"])], (
        "the dead-guard detector misjudged a synthetic guard: the dead_* guards import only the "
        "declared pyyaml, and each live_* guard imports a module no declared distribution provides"
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

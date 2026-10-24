# SPDX-License-Identifier: AGPL-3.0-or-later
"""The declared-dependency contract: what each source scope may import, and the files that import beyond it.

Every third-party import a source file requires must be satisfied by a
dependency declared for the run that loads that file, not by whatever another
requirement happens to pull in. A SourceScope pairs a selector of source files
with the extras, beside [project].dependencies, of the run that loads them;
each selector's docstring names that run. solar_challenge and tests are
first-party. A module a file names to pytest.importorskip as a string literal
counts as an import it requires, since the test skips wherever that module is
missing. So does the module pytest imports for each pytest_plugins entry, as
_pytest_plugin_imports reads them. _imports_required_by says when an import
inside a try block that handles ImportError counts, and dead_import_guards
finds each such guard over declared distributions only, whose handler can
never run. Imports map to distributions only through installed metadata, so a
scope's check skips where its extras are not installed.

The package's web subpackage, WEB_SUBPACKAGE, is first-party, yet any of its
modules may import the web extra at module top. So no file of
SCOPES_OUTSIDE_THE_PACKAGE_WITHOUT_THE_WEB_EXTRA may import one;
web_subpackage_imports finds each file that does.

Usage::

    from tests._declared_dependencies import (
        PACKAGE_SCOPES,
        SCOPES_OUTSIDE_THE_PACKAGE_WITHOUT_THE_WEB_EXTRA,
        SOURCE_SCOPES,
        SourceScope,
        assert_imports_only_declared,
        dead_import_guards,
        declared_distributions_or_skip,
        web_subpackage_imports,
    )

    @pytest.mark.parametrize("scope", SOURCE_SCOPES, ids=lambda scope: scope.name)
    def test_sources_import_only_declared_dependencies(project_root: Path, scope: SourceScope) -> None:
        assert_imports_only_declared(project_root, scope)

    for scope in PACKAGE_SCOPES:
        declared = declared_distributions_or_skip(project_root, scope.extras)
        dead = dead_import_guards(scope.select(project_root), declared)

    for scope in SCOPES_OUTSIDE_THE_PACKAGE_WITHOUT_THE_WEB_EXTRA:
        reached = web_subpackage_imports(project_root, scope.select(project_root))
"""

import ast
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from importlib.machinery import PathFinder
from importlib.metadata import PackageNotFoundError, distribution, packages_distributions
from pathlib import Path

import pytest
from _pytest.config import builtin_plugins
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tests._pyproject import core_requirements, extra_requirements

_IMPORT_FAILURES = {"ImportError", "ModuleNotFoundError"}
_PYTEST_PLUGINS = "pytest_plugins"
_NAMESPACE_FUNCTIONS = frozenset({"globals", "locals", "vars"})
_PACKAGE = "solar_challenge"
_FIRST_PARTY = frozenset({_PACKAGE, "tests"})
WEB_SUBPACKAGE = f"{_PACKAGE}.web"
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


def _src_dir(project_root: Path) -> Path:
    """Return *project_root*'s src/, which holds the package's source and from which the editable
    install imports it.
    """
    return project_root / "src"


def _package_dir(project_root: Path) -> Path:
    """Return the directory of the package under *project_root*, from which the editable install
    imports it.
    """
    return _src_dir(project_root) / _PACKAGE


def _web_subpackage_dir(project_root: Path) -> Path:
    """Return the directory of WEB_SUBPACKAGE, the package's web subpackage, under *project_root*:
    the one the web extra serves.
    """
    return _src_dir(project_root).joinpath(*WEB_SUBPACKAGE.split("."))


def _web_sources(project_root: Path) -> list[Path]:
    """Return the package's .py files inside its web subpackage, the one the web extra serves."""
    return list(_web_subpackage_dir(project_root).rglob("*.py"))


def _core_sources(project_root: Path) -> list[Path]:
    """Return the package's .py files outside its web subpackage, which an install of the package
    without extras runs.
    """
    return _python_files_outside(_package_dir(project_root), _web_subpackage_dir(project_root))


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
    import, transitively, as _imports_required_by reads each file's imports. A pytest_plugins
    entry and a module named to pytest.importorskip each count as an absolute import.

    Each of those modules runs in an offline-lane job that installs the dev extra alone, so a
    helper the verify also imports is judged here, against the dev extra alone, not with the
    verify's web extra. A module of the package that the files import stays with the package's
    own scope.
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
SCOPES_OUTSIDE_THE_PACKAGE_WITHOUT_THE_WEB_EXTRA: tuple[SourceScope, ...] = tuple(
    scope for scope in SOURCE_SCOPES if scope not in PACKAGE_SCOPES and WEB not in scope.extras
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


def _imports_in(tree: ast.AST) -> Iterator[ast.Import | ast.ImportFrom]:
    """Yield every import in *tree*, wherever it is."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node


def _unguarded_imports(nodes: Iterable[ast.AST]) -> Iterator[ast.Import | ast.ImportFrom]:
    """Yield the imports under *nodes*, skipping the body of every try that handles ImportError."""
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, ast.Try) and _handles_import_failure(node):
            yield from _unguarded_imports([*node.handlers, *node.orelse, *node.finalbody])
        else:
            yield from _unguarded_imports(ast.iter_child_nodes(node))


def _module_scope_statements(nodes: Iterable[ast.AST]) -> Iterator[ast.stmt]:
    """Yield the statements under *nodes* that run in their module's own scope: those in a block
    of a compound statement such as an if, a try or a with too, however deep.

    Not those in the body of a function or class, which runs in a scope of its own. The def or
    class itself is yielded.
    """
    for node in nodes:
        if isinstance(node, ast.stmt):
            yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield from _module_scope_statements(ast.iter_child_nodes(node))


def _nodes_outside_nested_statements(node: ast.AST) -> Iterator[ast.AST]:
    """Yield the nodes under *node*, a statement or a part of one, that lie under no statement
    nested in it: what the statement itself evaluates, such as its targets, values, tests and
    context managers, not what the statements of its blocks do.
    """
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, ast.stmt):
            yield child
            yield from _nodes_outside_nested_statements(child)


def _assignment_parts(statement: ast.stmt) -> tuple[list[ast.expr], ast.expr | None]:
    """Return (targets, value) for a *statement* that assigns, annotates or augments: the
    expressions it writes to, and the value it assigns or adds, None for an annotation with no
    value.

    Any other statement has no targets and no value.
    """
    if isinstance(statement, ast.Assign):
        return statement.targets, statement.value
    if isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
        return [statement.target], statement.value
    return [], None


def _binds_pytest_plugins(node: ast.AST) -> bool:
    """Return whether *node* is the name pytest_plugins as a target, the position that binds it."""
    return isinstance(node, ast.Name) and node.id == _PYTEST_PLUGINS and isinstance(node.ctx, ast.Store)


def _pytest_plugins_assignments(tree: ast.Module) -> Iterator[tuple[ast.stmt, ast.expr]]:
    """Yield (statement, value) for each statement of *tree*'s module scope, as
    _module_scope_statements finds them, that assigns pytest_plugins, annotated or not, or
    augments it. *value* is what the statement assigns or adds.

    pytest reads pytest_plugins as an attribute of the module once the module has run, so each
    such statement can give it entries. An annotation with no value assigns nothing.
    """
    for statement in _module_scope_statements(tree.body):
        targets, value = _assignment_parts(statement)
        if value is not None and any(_binds_pytest_plugins(target) for target in targets):
            yield statement, value


def _reads_or_deletes_pytest_plugins(node: ast.AST) -> bool:
    """Return whether *node* is the name pytest_plugins in a position that does not bind it: a read
    or a deletion.

    A read is how a method call such as append, a subscript or an alias changes the list the name
    holds.
    """
    return isinstance(node, ast.Name) and node.id == _PYTEST_PLUGINS and not isinstance(node.ctx, ast.Store)


def _is_namespace_entry_of_pytest_plugins(node: ast.AST) -> bool:
    """Return whether *node* is what globals(), locals() or vars() returns, subscripted with the
    str pytest_plugins, in any position: the entry of a namespace that may be the module's own.

    Whatever the call is given counts, so vars(module) does.
    """
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id in _NAMESPACE_FUNCTIONS
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == _PYTEST_PLUGINS
    )


def _unreadable_pytest_plugins_statements(tree: ast.Module) -> Iterator[ast.stmt]:
    """Yield each statement of *tree* that can bind or change pytest_plugins in a form
    _pytest_plugins_assignments does not read.

    In the module's scope, as _module_scope_statements finds them, one holds the name as a target
    other than the bare one of an assignment, an annotation or an augmentation: one of a tuple, a
    for, a with or a walrus. In any scope, one reads or deletes the name, through which a method
    call such as append, a subscript or an alias can change the list; subscripts globals(),
    locals() or vars() with the name; or declares it global, since a function or class that does
    can rebind the attribute of the module. A read in a function or class body counts even where
    the name is a local there, since scopes are not resolved.
    """
    for statement in _module_scope_statements(tree.body):
        read_targets, _ = _assignment_parts(statement)
        if any(
            _binds_pytest_plugins(node) and node not in read_targets
            for node in _nodes_outside_nested_statements(statement)
        ):
            yield statement
    for statement in (node for node in ast.walk(tree) if isinstance(node, ast.stmt)):
        if (isinstance(statement, ast.Global) and _PYTEST_PLUGINS in statement.names) or any(
            _reads_or_deletes_pytest_plugins(node) or _is_namespace_entry_of_pytest_plugins(node)
            for node in _nodes_outside_nested_statements(statement)
        ):
            yield statement


def _pytest_plugins_failure(source: Path, statement: ast.stmt, clause: str) -> AssertionError:
    """Return the failure for the pytest_plugins *statement* in *source* that the contract cannot
    follow. It names *source*, the line and the statement, quoted by its first line when it is
    compound; *clause* says what is wrong with it, such as "whose value is not a literal". It also
    says how to write pytest_plugins instead.
    """
    quoted = ast.unparse(statement).partition("\n")[0]
    return AssertionError(
        f"{source}:{statement.lineno} has `{quoted}`, {clause}; "
        "assign pytest_plugins, in the module's own scope, a literal list or tuple of module names "
        "or a comma-separated string, and add to it only with += and such a literal, "
        "for the declared-dependency contract to follow the plugins it names"
    )


def _pytest_plugin_imports(source: Path, tree: ast.Module) -> Iterator[ast.Import]:
    """Yield an import of the module pytest imports for each entry that the statements
    _pytest_plugins_assignments finds in *tree*, the syntax tree of *source*, give pytest_plugins.
    Each import sits where the value of its statement does.

    pytest imports each entry when it loads a conftest, test module or plugin that sets one. A
    built-in plugin's short name, such as pytester, names that module of pytest's own _pytest
    package, as PytestPluginManager.import_plugin reads builtin_plugins; any other entry names
    the module it spells. The entries are read without running *source*, so each value must be a
    literal: a str, whose entries are its pieces between commas, or a list or tuple of str. None
    names no plugin. Any other value fails, naming *source*, the line and the statement, and so
    does a statement that _unreadable_pytest_plugins_statements finds.

    Each statement's value is read on its own, not added to what the module held before it. That
    is why a str's empty pieces are dropped, such as the one before the comma of `+= ",x"`, and why
    a str added to a list reads as the module it spells, not as the characters list.extend adds.
    """
    unreadable = next(_unreadable_pytest_plugins_statements(tree), None)
    if unreadable is not None:
        raise _pytest_plugins_failure(
            source, unreadable, "which can bind or change pytest_plugins in a form the contract cannot read"
        )
    for statement, value in _pytest_plugins_assignments(tree):
        try:
            plugins = ast.literal_eval(value)
        except ValueError:
            raise _pytest_plugins_failure(source, statement, "whose value is not a literal") from None
        if plugins is None:
            continue
        if not isinstance(plugins, (str, list, tuple)):
            raise _pytest_plugins_failure(
                source, statement, "whose value is neither a str nor a list or tuple"
            )
        entries = [piece for piece in plugins.split(",") if piece] if isinstance(plugins, str) else plugins
        for entry in entries:
            if not isinstance(entry, str):
                raise _pytest_plugins_failure(
                    source, statement, f"whose value names {entry!r}, not a module name"
                )
            module = f"_pytest.{entry}" if entry in builtin_plugins else entry
            yield ast.copy_location(ast.Import(names=[ast.alias(name=module)]), value)


def _calls_importorskip(call: ast.Call) -> bool:
    """Return whether *call* is spelled as a call of pytest's importorskip: pytest.importorskip, or
    the bare importorskip that `from pytest import importorskip` binds.

    Only the spelling is read, not what its names are bound to, so a method of that name on any
    other object, or on pytest imported under another name, is no match.
    """
    callee = call.func
    if isinstance(callee, ast.Attribute):
        return (
            callee.attr == "importorskip"
            and isinstance(callee.value, ast.Name)
            and callee.value.id == "pytest"
        )
    return isinstance(callee, ast.Name) and callee.id == "importorskip"


def _importorskip_imports(tree: ast.AST) -> Iterator[ast.Import]:
    """Yield an import of each module an importorskip call in *tree* passes as a string literal,
    positionally or as modname=, wherever the call is. Each import sits where its literal does.

    The call imports the module or skips its test, and an ImportError handler around it cannot
    catch the skip, so the file requires the module wherever the call is. A modname that is not
    a string literal is not read.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _calls_importorskip(node):
            keyword_modnames = [keyword.value for keyword in node.keywords if keyword.arg == "modname"]
            for modname in [*node.args[:1], *keyword_modnames]:
                if isinstance(modname, ast.Constant) and isinstance(modname.value, str):
                    yield ast.copy_location(ast.Import(names=[ast.alias(name=modname.value)]), modname)


def _imports_required_by(project_root: Path, source: Path) -> Iterator[ast.Import | ast.ImportFrom]:
    """Yield the imports the Python *source* file of *project_root* requires: its own imports, an
    import of each module it names to pytest.importorskip, and an import of the module pytest
    imports for each entry of its pytest_plugins.

    Every reading of what a file requires starts here. A file's own imports are its
    _unguarded_imports in the package, and every import in it, guarded or not, anywhere else.
    """
    tree = _parse(source)
    if source.is_relative_to(_package_dir(project_root)):
        yield from _unguarded_imports([tree])
    else:
        yield from _imports_in(tree)
    yield from _importorskip_imports(tree)
    yield from _pytest_plugin_imports(source, tree)


def _directory_of_absolute_name(project_root: Path, name: str) -> Path:
    """Return the directory the absolute dotted *name* resolves from: *project_root*'s src/ for a
    name of the package, where the editable install finds it, and *project_root* for any other.
    """
    return _src_dir(project_root) if name.partition(".")[0] == _PACKAGE else project_root


def _directory_of_from_import(project_root: Path, source: Path, node: ast.ImportFrom) -> Path:
    """Return the directory the from-import *node* of *source* resolves from: as
    _directory_of_absolute_name gives for an absolute import, else *source*'s package directory,
    climbed level - 1 times.

    A level that climbs out of *project_root*, even to above the filesystem root, fails naming
    *source*, the line and the import: Python rejects a relative import beyond its top-level
    package.
    """
    if not node.level:
        return _directory_of_absolute_name(project_root, node.module or "")
    directory = source.parents[: node.level][-1]
    assert directory.is_relative_to(project_root), (
        f"{source}:{node.lineno} imports `{ast.unparse(node)}`, which climbs out of {project_root}; "
        "a relative import cannot leave its top-level package"
    )
    return directory


def _import_targets(project_root: Path, source: Path) -> Iterator[tuple[Path, list[str]]]:
    """Yield (directory, dotted-name parts) for each module *source* may import.

    An absolute name of the package resolves from *project_root*'s src/, where the editable
    install finds it, any other absolute name from *project_root*, and a relative one from
    *source*'s package directory. Imports count as _imports_required_by reads them. The last
    part of a from-import's name may be an attribute of the module before it, not a module.

    A relative import that climbs out of *project_root*, or a pytest_plugins that
    _pytest_plugin_imports cannot read, fails naming *source* and the line.
    """
    for node in _imports_required_by(project_root, source):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield _directory_of_absolute_name(project_root, alias.name), alias.name.split(".")
        else:
            directory = _directory_of_from_import(project_root, source, node)
            module_parts = node.module.split(".") if node.module else []
            for alias in node.names:
                yield directory, [*module_parts, alias.name]


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


def _files_its_imports_run(project_root: Path, source: Path) -> Iterator[Path]:
    """Yield the files that importing each module *source* may import runs, as _import_targets
    reads its imports and _files_run_by_importing finds their files.
    """
    for directory, parts in _import_targets(project_root, source):
        yield from _files_run_by_importing(directory, parts)


def _with_the_tests_modules_they_import(project_root: Path, sources: list[Path]) -> list[Path]:
    """Return *sources* and every module of the tests package that they import, transitively."""
    tests_dir = project_root / "tests"
    selected = dict.fromkeys(sources)
    pending = list(sources)
    while pending:
        source = pending.pop()
        for module_file in _files_its_imports_run(project_root, source):
            if module_file.is_relative_to(tests_dir) and module_file not in selected:
                selected[module_file] = None
                pending.append(module_file)
    return list(selected)


def web_subpackage_imports(project_root: Path, sources: Iterable[Path]) -> list[tuple[Path, list[Path]]]:
    """Return (file, web files run) for every file in *sources* whose imports run a file of
    WEB_SUBPACKAGE under *project_root*.

    Imports count as _imports_required_by reads them; it also says when an import inside a try
    that handles ImportError counts. A function-local import, a TYPE_CHECKING import, a module
    named to pytest.importorskip and a pytest_plugins entry count. Names resolve as Python finds
    them, so a module named web elsewhere is not the subpackage. Only files are read; no
    installed metadata is needed.

    Each file's own imports are read, not those of the package's modules it imports. That is
    enough because, outside the subpackage, the package imports it only inside a function, as
    tests/unit/test_import_structure.py::test_no_module_outside_the_web_subpackage_imports_it_at_module_top
    pins. So importing a module of the package outside the subpackage runs no file of the
    subpackage.
    """
    web_dir = _web_subpackage_dir(project_root)
    reaching: list[tuple[Path, list[Path]]] = []
    for source in sources:
        web_files = sorted(
            {
                module_file
                for module_file in _files_its_imports_run(project_root, source)
                if module_file.is_relative_to(web_dir)
            }
        )
        if web_files:
            reaching.append((source, web_files))
    return sorted(reaching)


def _top_level_modules(imports: Iterable[ast.Import | ast.ImportFrom]) -> set[str]:
    """Return the top-level module of every absolute import among *imports*."""
    modules: set[str] = set()
    for node in imports:
        if isinstance(node, ast.Import):
            modules.update(alias.name.partition(".")[0] for alias in node.names)
        elif node.level == 0 and node.module:
            modules.add(node.module.partition(".")[0])
    return modules


def _required_top_level_modules(project_root: Path, sources: Iterable[Path]) -> set[str]:
    """Return the top-level module of every absolute import *sources*, files of *project_root*,
    require, as _imports_required_by reads them.

    Function-local and TYPE_CHECKING imports count; relative imports do not.
    """
    return _top_level_modules(
        node for source in sources for node in _imports_required_by(project_root, source)
    )


def _third_party_modules(modules: set[str]) -> set[str]:
    """Return *modules* without the standard library and the first-party solar_challenge and
    tests packages.
    """
    return modules - sys.stdlib_module_names - _FIRST_PARTY


def _third_party_distributions(
    project_root: Path, source: Path, providers: Mapping[str, list[str]]
) -> set[str]:
    """Return the canonical names of the distributions that provide the third-party modules
    *source*, a file of *project_root*, requires, as *providers* maps modules to distributions.

    Standard-library modules and the first-party solar_challenge and tests packages are dropped.
    """
    third_party = _third_party_modules(_required_top_level_modules(project_root, [source]))
    unprovided = sorted(module for module in third_party if module not in providers)
    assert not unprovided, (
        f"no installed distribution provides the modules {source} requires: {unprovided}; "
        "declare and install the distribution that provides them"
    )
    return {canonicalize_name(dist) for module in third_party for dist in providers[module]}


def undeclared_distributions(
    project_root: Path,
    sources: Iterable[Path],
    declared: set[str],
) -> list[tuple[Path, list[str]]]:
    """Return (file, undeclared distributions) for every file in *sources*, files of
    *project_root*, that requires a third-party distribution outside *declared*.
    """
    providers = packages_distributions()
    undeclared: list[tuple[Path, list[str]]] = []
    for source in sources:
        distributions = sorted(_third_party_distributions(project_root, source, providers) - declared)
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
        yield from _imports_in(statement)


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
        for source, distributions in undeclared_distributions(project_root, sources, declared)
    ]
    groups = ", ".join(
        ["[project].dependencies", *(f"[project.optional-dependencies].{extra}" for extra in scope.extras)]
    )
    assert not undeclared, (
        f"these files require distributions missing from {groups}: {undeclared}. "
        "A module a file names to pytest.importorskip counts as required, since its test skips "
        "wherever the module is missing; so does a plugin module a pytest_plugins entry names, "
        "since pytest imports it when it loads the file; and so, outside src/solar_challenge, does "
        "an import inside a try block that handles ImportError. Declare them in one of those groups "
        "in pyproject.toml, or, in src/solar_challenge, make the import optional inside a try block "
        "that handles ImportError"
    )

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import-structure contract tests: which modules the import statements of solar_challenge may name.

INV-5: no import statement inside a function of solar_challenge names another of its modules,
except for the (importing module, imported module) pairs ALLOWED_FUNCTION_LOCAL_IMPORTS
lists. Each pair carries a Permanent reason, the documented contract that requires the
laziness, or a Transitional one, the task or program stream that removes the import.
The check runs both ways, so the change that removes a pair's last such import deletes
its entry. docs/prds/errors-leaf.md §7 measured and classified the list.

No import statement of solar_challenge, at any scope, names the tests package: the wheel
ships only src/, so such an import fails in every installed copy.

Outside its web subpackage, no import statement of solar_challenge names a module of that
subpackage outside a function. Any module of the subpackage may import the web extra at
module top, and the CLI, scripts/ and the dev-only offline-lane jobs run without that extra.
ALLOWED_FUNCTION_LOCAL_IMPORTS lists the function-local imports that reach the subpackage.

web/database.py, the leaf of the run store's persistence stratum, imports no module of the
web subpackage at any scope (docs/prds/run-store-one-owner.md §4): every table owner and
web/schema.py import it (§3.1), so such an import closes a cycle or reaches up the stratum.
No ALLOWED_FUNCTION_LOCAL_IMPORTS entry exempts one.

web/field_tree.py, the stored-run format's field-tree codec, imports no module of
solar_challenge at any scope: it reads any dataclass through its annotations, so it needs none,
and modules of the web subpackage import it, web/stored_runs.py among them (§3.1), so an
import of a web module would close a cycle or reach up past its importers.

scenario_blocks.py, the scenario grammar's block readers, imports neither fleet_distribution
nor config at any scope (docs/prds/scenario-grammar-partition.md §4.2 C1): both read their
blocks through it, so such an import closes a cycle.

These rules read import statements only: the lazy loader in solar_challenge/__init__.py
(`__getattr__`, which calls importlib.import_module) is pinned by
tests/unit/test_public_api_surface.py. One test reads what an import loads instead, from a
fresh interpreter's sys.modules: importing scenario_blocks loads neither fleet_distribution nor
config, so no module that scenario_blocks imports reaches them either.
"""

import ast
from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import astuple, dataclass
from enum import Enum
from pathlib import Path

import pytest

from tests._declared_dependencies import WEB_SUBPACKAGE
from tests._modules_loaded_by_importing import package_modules_loaded_by_importing
from tests._repository_paths import REPOSITORY_ROOT

_PACKAGE = "solar_challenge"
_TEST_SUITE = "tests"
_WEB_DATABASE = f"{WEB_SUBPACKAGE}.database"
_WEB_FIELD_TREE = f"{WEB_SUBPACKAGE}.field_tree"
_SCENARIO_BLOCKS = f"{_PACKAGE}.scenario_blocks"
_FLEET_DISTRIBUTION = f"{_PACKAGE}.fleet_distribution"
_CONFIG = f"{_PACKAGE}.config"
#: The scenario grammar's strata, lowest first: no module of one imports a module of a higher one.
_GRAMMAR_STRATA: tuple[tuple[str, ...], ...] = (
    (f"{_PACKAGE}.errors", f"{_PACKAGE}.number_fields"),
    (_SCENARIO_BLOCKS,),
    (_FLEET_DISTRIBUTION,),
    (_CONFIG,),
)
#: The grammar modules: those of every stratum above the lowest, whose leaves the grammar imports.
_GRAMMAR_MODULES: tuple[str, ...] = tuple(
    module for stratum in _GRAMMAR_STRATA[1:] for module in stratum
)
_RUNNER_PREFIX = "simulate_"
_SRC_DIR = REPOSITORY_ROOT / "src"


@dataclass(frozen=True)
class Permanent:
    """The documented contract that requires an import to stay inside a function."""

    contract: str


@dataclass(frozen=True)
class Transitional:
    """The task or program stream that moves an import to module top or deletes it."""

    owner: str


_CLI_WITHOUT_THE_WEB_EXTRA = Permanent(
    "the optional web extra: the CLI runs without it (README.md, Installation), and any module "
    "of the web subpackage may import the extra at module top "
    "(tests/unit/test_dependency_declarations.py), so the CLI reaches the web subpackage only "
    "inside `web start` and `web migrate`"
)
_FINANCE_PARTITION = Transitional(
    "program stream S8, the finance partition "
    "(plans/review-all-program-solar_challenge-20261014.md)"
)

ALLOWED_FUNCTION_LOCAL_IMPORTS: dict[tuple[str, str], Permanent | Transitional] = {
    ("solar_challenge", "solar_challenge.cli"): Permanent(
        "the cheap top-level import: `import solar_challenge` loads no submodule until a public "
        "name is accessed, and the CLI loads pvlib, Typer and Rich "
        "(docs/domain-library-consumption.md, Cheap top-level import; "
        "tests/unit/test_public_api_surface.py::test_import_is_pvlib_free)"
    ),
    ("solar_challenge.cli.web", "solar_challenge.web"): _CLI_WITHOUT_THE_WEB_EXTRA,
    ("solar_challenge.cli.web", "solar_challenge.web.app"): _CLI_WITHOUT_THE_WEB_EXTRA,
    ("solar_challenge.cli.web", "solar_challenge.web.jobs"): _CLI_WITHOUT_THE_WEB_EXTRA,
    ("solar_challenge.cli.web", "solar_challenge.web.reloader"): _CLI_WITHOUT_THE_WEB_EXTRA,
    ("solar_challenge.cli.web", "solar_challenge.web.schema"): _CLI_WITHOUT_THE_WEB_EXTRA,
    ("solar_challenge.cli.web", "solar_challenge.web.store_lock"): _CLI_WITHOUT_THE_WEB_EXTRA,
    ("solar_challenge.web", "solar_challenge.web.app"): Permanent(
        "the optional web extra: importing any web submodule runs web/__init__.py, and the web "
        "submodules that need no Flask import without the extra "
        "(tests/unit/test_conftests_need_no_web_extra.py) only while create_app defers web.app, "
        "which imports Flask"
    ),

    ("solar_challenge.finance", "solar_challenge.battery"): _FINANCE_PARTITION,
    ("solar_challenge.finance", "solar_challenge.fleet"): _FINANCE_PARTITION,
    ("solar_challenge.finance", "solar_challenge.home"): _FINANCE_PARTITION,
    ("solar_challenge.finance", "solar_challenge.pv"): _FINANCE_PARTITION,
    ("solar_challenge.load", "solar_challenge.ev"): Transitional(
        "program stream S12, load composition"
    ),
}


@dataclass(frozen=True)
class _ImportSite:
    """One module an import statement of the package imports: the importing and imported modules, the statement's file and line, whether it sits inside a function, and the names a from-import binds from the module, as written there, never their aliases."""

    importer: str
    imported: str
    path: Path
    line: int
    in_function: bool
    names: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line} imports {self.imported}"


class _GrammarRule(Enum):
    """A rule of the scenario grammar's contract (docs/prds/scenario-grammar-partition.md §4.2), its value the invariant's text."""

    IMPORT_DIRECTION = (
        "C1: the scenario grammar imports in one direction, errors, number_fields <- "
        "scenario_blocks <- fleet_distribution <- config, at any scope"
    )
    NO_RUNNER = "C2: no grammar module imports a simulate_* runner"
    ONE_SPELLING = "C3: a grammar name is imported from the module that defines it"
    NO_PRIVATE_NAME = "C3: no module imports an underscore name from a grammar module"


@dataclass(frozen=True)
class _GrammarViolation:
    """A statement of the package that breaks a rule of the grammar: its file and line, the rule, the module or name it breaks the rule with, and what it does, in prose."""

    path: Path
    line: int
    rule: _GrammarRule
    subject: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line}: {self.detail} ({self.rule.value})"


def _module_name(source: Path, src_dir: Path) -> str:
    """Return the dotted name of the module *source* under *src_dir*; an __init__.py names its package."""
    parts = source.relative_to(src_dir).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _from_module(node: ast.ImportFrom, importer: str, is_package: bool) -> str:
    """Return the dotted name of the module or package *node*'s `from` clause names, resolving a relative one against *importer*'s package."""
    if node.level == 0:
        return node.module or ""
    package = importer if is_package else importer.rpartition(".")[0]
    base = package.rsplit(".", node.level - 1)[0]
    return f"{base}.{node.module}" if node.module else base


def _imported_modules_and_names(
    node: ast.Import | ast.ImportFrom, importer: str, is_package: bool
) -> list[tuple[str, tuple[str, ...]]]:
    """Return the dotted name of each module *node* imports, with the names it binds from that module; a from-import with no module or of the top-level package names each alias as a module of it, however it is spelled, binding no name from it."""
    if isinstance(node, ast.Import):
        return [(alias.name, ()) for alias in node.names]
    from_module = _from_module(node, importer, is_package)
    if node.module is None or from_module == _PACKAGE:
        return [(f"{from_module}.{alias.name}", ()) for alias in node.names]
    return [(from_module, tuple(alias.name for alias in node.names))]


def _import_statements(
    node: ast.AST, in_function: bool = False
) -> Iterator[tuple[ast.Import | ast.ImportFrom, bool]]:
    """Yield, once each and in source order, the imports under *node*, each with whether it sits inside a function or method."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            yield child, in_function
        yield from _import_statements(
            child, in_function or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        )


def _import_sites(
    src_dir: Path, package: str = _PACKAGE, root: Path | None = None
) -> list[_ImportSite]:
    """Return a site for every module an import statement of *package*, the top-level package under *src_dir*, imports, at any scope, in path then line order; each path is relative to *root*, *src_dir*'s parent unless given."""
    paths_from = src_dir.parent if root is None else root
    sites: list[_ImportSite] = []
    for source in sorted((src_dir / package).rglob("*.py")):
        importer = _module_name(source, src_dir)
        path = source.relative_to(paths_from)
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node, in_function in _import_statements(tree):
            imports = _imported_modules_and_names(node, importer, source.name == "__init__.py")
            for imported, names in imports:
                sites.append(_ImportSite(importer, imported, path, node.lineno, in_function, names))
    return sites


def _in_package(module: str, package: str) -> bool:
    """Return whether *module* is *package* or a module beneath it."""
    return module == package or module.startswith(f"{package}.")


def _function_local_package_imports(sites: Iterable[_ImportSite]) -> list[_ImportSite]:
    """Return the *sites* that import a module of the package inside a function."""
    return [site for site in sites if site.in_function and _in_package(site.imported, _PACKAGE)]


def _test_suite_imports(sites: Iterable[_ImportSite]) -> list[_ImportSite]:
    """Return the *sites* that import the tests package or a module beneath it, at any scope."""
    return [site for site in sites if _in_package(site.imported, _TEST_SUITE)]


def _module_top_imports_into_the_web_subpackage(sites: Iterable[_ImportSite]) -> list[_ImportSite]:
    """Return the *sites* of modules outside the web subpackage that import a module of it outside any function."""
    return [
        site
        for site in sites
        if not site.in_function
        and _in_package(site.imported, WEB_SUBPACKAGE)
        and not _in_package(site.importer, WEB_SUBPACKAGE)
    ]


def _imports_by(importer: str, package: str, sites: Iterable[_ImportSite]) -> list[_ImportSite]:
    """Return the *sites* at which module *importer* imports *package* or a module beneath it, at any scope."""
    return [
        site
        for site in sites
        if site.importer == importer and _in_package(site.imported, package)
    ]


def _grammar_modules_above(module: str) -> tuple[str, ...]:
    """Return the modules of every grammar stratum above *module*'s, lowest first; () for a module of the top stratum or of none."""
    for level, stratum in enumerate(_GRAMMAR_STRATA):
        if module in stratum:
            return tuple(above for higher in _GRAMMAR_STRATA[level + 1 :] for above in higher)
    return ()


def _grammar_layering_violations(sites: Iterable[_ImportSite]) -> list[_GrammarViolation]:
    """Return, in path then line order, each of *sites* at which a module of a grammar stratum imports a module of a higher one, or a module beneath it, and each simulate_* name a grammar module imports from a module of the package."""
    violations: list[_GrammarViolation] = []
    for site in sites:
        if any(_in_package(site.imported, above) for above in _grammar_modules_above(site.importer)):
            violations.append(
                _GrammarViolation(
                    site.path,
                    site.line,
                    _GrammarRule.IMPORT_DIRECTION,
                    site.imported,
                    f"{site.importer} imports {site.imported}",
                )
            )
        if site.importer in _GRAMMAR_MODULES and _in_package(site.imported, _PACKAGE):
            violations.extend(
                _GrammarViolation(
                    site.path,
                    site.line,
                    _GrammarRule.NO_RUNNER,
                    name,
                    f"{site.importer} imports {name} from {site.imported}",
                )
                for name in site.names
                if name.startswith(_RUNNER_PREFIX)
            )
    return sorted(violations, key=lambda violation: (violation.path, violation.line))


def _src_and_test_import_sites(root: Path) -> list[_ImportSite]:
    """Return the import sites of the package under root/src and of the tests package under *root*, at any scope, each path relative to *root*."""
    return [*_import_sites(root / "src"), *_import_sites(root, package=_TEST_SUITE, root=root)]


def _bound_names(target: ast.expr) -> Iterator[str]:
    """Yield each name an assignment to *target* binds, unpacking tuples, lists and starred targets."""
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _bound_names(element)
    elif isinstance(target, ast.Starred):
        yield from _bound_names(target.value)


def _top_level_names(statements: Iterable[ast.stmt]) -> Iterator[str]:
    """Yield each name *statements* bind by def, async def, class, assignment or annotated assignment, those of an if's or a try's bodies included, never by an import."""
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield statement.name
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                yield from _bound_names(target)
        elif isinstance(statement, ast.AnnAssign):
            yield from _bound_names(statement.target)
        elif isinstance(statement, ast.If):
            yield from _top_level_names([*statement.body, *statement.orelse])
        elif isinstance(statement, ast.Try):
            handled = [line for handler in statement.handlers for line in handler.body]
            yield from _top_level_names(
                [*statement.body, *handled, *statement.orelse, *statement.finalbody]
            )


def _defined_names(source: str) -> frozenset[str]:
    """Return the names the module whose text is *source* defines at top level, as _top_level_names reads them."""
    return frozenset(_top_level_names(ast.parse(source).body))


def _definers(src_dir: Path) -> Mapping[str, tuple[str, ...]]:
    """Return, for each name a module of the package under *src_dir* defines, the modules that define it, in path order."""
    definers: dict[str, list[str]] = {}
    for source in sorted((src_dir / _PACKAGE).rglob("*.py")):
        module = _module_name(source, src_dir)
        for name in _defined_names(source.read_text(encoding="utf-8")):
            definers.setdefault(name, []).append(module)
    return {name: tuple(modules) for name, modules in definers.items()}


def _one_spelling_violations(sites: Iterable[_ImportSite], src_dir: Path) -> list[_GrammarViolation]:
    """Return, in path then line order, each name the *sites* import from a grammar module that is an underscore name, or that the module does not define, as the package under *src_dir* defines its names."""
    definers = _definers(src_dir)
    violations: list[_GrammarViolation] = []
    for site in sites:
        if site.imported not in _GRAMMAR_MODULES:
            continue
        for name in site.names:
            imports = f"{site.importer} imports {name} from {site.imported}"
            defined_by = definers.get(name, ())
            if name.startswith("_"):
                rule, detail = _GrammarRule.NO_PRIVATE_NAME, imports
            elif site.imported in defined_by:
                continue
            elif defined_by:
                rule, detail = _GrammarRule.ONE_SPELLING, f"{imports}, which {' and '.join(defined_by)} defines"
            else:
                rule, detail = _GrammarRule.ONE_SPELLING, f"{imports}, and no module of the package defines it"
            violations.append(_GrammarViolation(site.path, site.line, rule, name, detail))
    return sorted(violations, key=lambda violation: (violation.path, violation.line))


def _unlisted(
    found: Iterable[_ImportSite], allowed: Collection[tuple[str, str]]
) -> list[_ImportSite]:
    """Return the *found* sites whose (importing module, imported module) pair is not in *allowed*."""
    return [site for site in found if (site.importer, site.imported) not in allowed]


def _stale(
    found: Iterable[_ImportSite], allowed: Collection[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Return the sorted pairs of *allowed* that no *found* site imports."""
    imported = {(site.importer, site.imported) for site in found}
    return sorted(set(allowed) - imported)


@pytest.fixture(scope="module")
def real_tree_imports() -> tuple[_ImportSite, ...]:
    """The import sites of src/solar_challenge, at any scope, scanned once for every real-tree test."""
    return tuple(_import_sites(_SRC_DIR))


@pytest.fixture(scope="module")
def real_tree_src_and_test_imports() -> tuple[_ImportSite, ...]:
    """The import sites of src/solar_challenge and of tests, at any scope, scanned once for the one-spelling tests."""
    return tuple(_src_and_test_import_sites(REPOSITORY_ROOT))


def test_every_function_local_package_import_is_allowed(
    real_tree_imports: tuple[_ImportSite, ...],
) -> None:
    """Every import of a module of the package inside a function is of a pair ALLOWED_FUNCTION_LOCAL_IMPORTS lists."""
    unlisted = _unlisted(
        _function_local_package_imports(real_tree_imports), ALLOWED_FUNCTION_LOCAL_IMPORTS
    )

    sites = "\n".join(str(site) for site in unlisted)
    assert not unlisted, (
        "these imports of the package sit inside a function, and ALLOWED_FUNCTION_LOCAL_IMPORTS "
        "in tests/unit/test_import_structure.py lists no entry for their (importing module, "
        f"imported module) pair:\n{sites}\n"
        "Import the module at the top of the importing module. If a documented contract "
        "requires the laziness, add the pair as Permanent(<contract>); if a task or program "
        "stream will remove the import, add it as Transitional(<owner>)"
    )


def test_every_allowed_pair_is_still_imported_inside_a_function(
    real_tree_imports: tuple[_ImportSite, ...],
) -> None:
    """Every pair ALLOWED_FUNCTION_LOCAL_IMPORTS lists is still imported inside a function of the package."""
    stale = _stale(
        _function_local_package_imports(real_tree_imports), ALLOWED_FUNCTION_LOCAL_IMPORTS
    )

    entries = "\n".join(f"{pair}: {ALLOWED_FUNCTION_LOCAL_IMPORTS[pair]!r}" for pair in stale)
    assert not stale, (
        "no function in src/solar_challenge imports these (importing module, imported module) "
        "pairs any more, so their entries go from ALLOWED_FUNCTION_LOCAL_IMPORTS in "
        f"tests/unit/test_import_structure.py, in the change that removed the import:\n{entries}"
    )


def test_every_allowed_pair_names_a_contract_or_an_owner() -> None:
    """Every allowed pair's reason is a Permanent with a contract or a Transitional with an owner, not blank text."""
    reason_kinds = (Permanent, Transitional)
    unreasoned = {
        pair: reason
        for pair, reason in ALLOWED_FUNCTION_LOCAL_IMPORTS.items()
        if not isinstance(reason, reason_kinds) or not all(text.strip() for text in astuple(reason))
    }

    entries = "\n".join(f"{pair}: {reason!r}" for pair, reason in unreasoned.items())
    assert not unreasoned, (
        "these allowed pairs give no reason; each must be a Permanent(<the documented contract "
        "that requires the laziness>) or a Transitional(<the task or program stream that "
        f"removes the import>), with non-blank text:\n{entries}"
    )


def test_no_import_statement_of_the_package_names_the_test_suite(
    real_tree_imports: tuple[_ImportSite, ...],
) -> None:
    """No import statement of the package, at any scope, imports the tests package, which the wheel does not ship."""
    found = _test_suite_imports(real_tree_imports)

    sites = "\n".join(str(site) for site in found)
    assert not found, (
        "these import statements of src/solar_challenge import the tests package, and the wheel "
        "ships only the packages under src/ (pyproject.toml, [tool.setuptools.packages.find]), "
        f"so each fails with ModuleNotFoundError in every installed copy:\n{sites}\n"
        "Move what the package needs from tests/ into src/solar_challenge, or move the code "
        "that needs the tests package into tests/"
    )


def test_no_module_outside_the_web_subpackage_imports_it_at_module_top(
    real_tree_imports: tuple[_ImportSite, ...],
) -> None:
    """Outside its web subpackage, the package imports a module of that subpackage only inside a function, since any of its modules may import the web extra at module top. The CLI, scripts/ and the offline lane's dev-only jobs run without that extra, and web_subpackage_imports in tests/_declared_dependencies.py reads only those files' own imports, relying on this rule."""
    found = _module_top_imports_into_the_web_subpackage(real_tree_imports)

    sites = "\n".join(str(site) for site in found)
    assert not found, (
        "these import statements of src/solar_challenge, outside its web subpackage, import a "
        f"module of that subpackage outside any function:\n{sites}\n"
        "Any module of the web subpackage may import the web extra at module top (the contract "
        "_CLI_WITHOUT_THE_WEB_EXTRA states), so importing the module that holds such an import "
        "needs that extra. An import in a TYPE_CHECKING block counts too: it never runs, but a "
        "module outside the subpackage should not need the subpackage even for its annotations. "
        "The CLI, scripts/ and the offline lane's dev-only jobs run without the web extra, and "
        "web_subpackage_imports in tests/_declared_dependencies.py reads only those files' own "
        "imports, relying on this rule. Import the module inside the function that needs the web "
        "extra, as cli/web.py's start and _serve do, and list the pair in "
        "ALLOWED_FUNCTION_LOCAL_IMPORTS with the Permanent reason _CLI_WITHOUT_THE_WEB_EXTRA; or "
        "move the code that needs it into the web subpackage"
    )


def test_web_database_imports_no_module_of_the_web_subpackage(
    real_tree_imports: tuple[_ImportSite, ...],
) -> None:
    """web/database.py imports no module of the web subpackage, at any scope."""
    found = _imports_by(_WEB_DATABASE, WEB_SUBPACKAGE, real_tree_imports)

    sites = "\n".join(str(site) for site in found)
    assert not found, (
        "these import statements of web/database.py import a module of the web subpackage:"
        f"\n{sites}\n"
        "database.py is the leaf of the persistence stratum and imports no solar_challenge.web "
        "module at any scope (docs/prds/run-store-one-owner.md §4)"
    )


def test_the_scan_reads_the_imports_of_web_database(
    real_tree_imports: tuple[_ImportSite, ...],
) -> None:
    """The scan reads the import statements of web/database.py, so the leaf rule cannot pass by reading none once the module is renamed or moved."""
    importers = {site.importer for site in real_tree_imports}

    assert _WEB_DATABASE in importers, (
        f"the scan of src/solar_challenge read no import statement of {_WEB_DATABASE}, so "
        "test_web_database_imports_no_module_of_the_web_subpackage checks nothing. If the module "
        "was renamed or moved, point _WEB_DATABASE at the module that holds Database and "
        "TableSchema, and update docs/prds/run-store-one-owner.md §3.1 and §4 with it"
    )


def test_web_field_tree_imports_no_module_of_the_package(
    real_tree_imports: tuple[_ImportSite, ...],
) -> None:
    """web/field_tree.py imports no module of solar_challenge, at any scope."""
    found = _imports_by(_WEB_FIELD_TREE, _PACKAGE, real_tree_imports)

    sites = "\n".join(str(site) for site in found)
    assert not found, (
        "these import statements of web/field_tree.py import a module of solar_challenge:"
        f"\n{sites}\n"
        "field_tree.py is the stored-run format's field-tree codec. It reads any dataclass "
        "through the class's annotations, so it needs no module of the package, and modules of "
        "the web subpackage import it, web/stored_runs.py among them, so an import of a web module "
        "closes a cycle or reaches up past its importers (docs/prds/run-store-one-owner.md §3.1). "
        "Keep what needs the package in the codec's callers, such as web/stored_runs.py"
    )


def test_the_scan_reads_the_imports_of_web_field_tree(
    real_tree_imports: tuple[_ImportSite, ...],
) -> None:
    """The scan reads the import statements of web/field_tree.py, so its leaf rule cannot pass by reading none once the module is renamed or moved."""
    importers = {site.importer for site in real_tree_imports}

    assert _WEB_FIELD_TREE in importers, (
        f"the scan of src/solar_challenge read no import statement of {_WEB_FIELD_TREE}, so "
        "test_web_field_tree_imports_no_module_of_the_package checks nothing. If the "
        "module was renamed or moved, point _WEB_FIELD_TREE at the module that holds "
        "read_field_tree, and update docs/prds/run-store-one-owner.md §3.1 with it"
    )


@pytest.mark.parametrize(
    "module",
    [
        pytest.param(module, id=module.rpartition(".")[2])
        for module in _GRAMMAR_MODULES
        if _grammar_modules_above(module)
    ],
)
def test_importing_a_grammar_module_loads_no_grammar_module_above_it(module: str) -> None:
    """A fresh interpreter that imports a grammar module has loaded no grammar module above it, so no module it imports reaches up into the grammar that reads through it."""
    loaded = package_modules_loaded_by_importing(module)

    grammar_loaded = sorted(set(_grammar_modules_above(module)) & loaded)
    assert not grammar_loaded, (
        f"importing {module} in a fresh interpreter loads {', '.join(grammar_loaded)}. "
        "The scenario grammar imports in one direction, errors, number_fields <- scenario_blocks "
        "<- fleet_distribution <- config (docs/prds/scenario-grammar-partition.md §4.2 C1), so "
        f"neither {module} nor any module it imports may load the grammar above it"
    )


def test_the_scenario_grammar_imports_in_one_direction_and_imports_no_runner(
    real_tree_imports: tuple[_ImportSite, ...],
) -> None:
    """No module of a grammar stratum imports a module of a higher one, at any scope, and no grammar module imports a simulate_* name from a module of the package."""
    found = _grammar_layering_violations(real_tree_imports)

    violations = "\n".join(str(violation) for violation in found)
    assert not found, (
        f"these import statements of src/solar_challenge break the scenario grammar's layering:\n"
        f"{violations}\n"
        "Each grammar module reads its blocks through the modules below it, so an import against "
        "the direction closes a cycle: move what a lower module needs down into it. A grammar "
        "module reads homes, never simulates them: call the runner from the code that reads the "
        "document (docs/prds/scenario-grammar-partition.md §4.2 C1 and C2)"
    )


def test_the_scan_reads_the_imports_of_every_grammar_module(
    real_tree_imports: tuple[_ImportSite, ...],
) -> None:
    """The scan reads the import statements of every grammar module, so the layering rules cannot pass by reading none once a module is renamed or moved."""
    importers = {site.importer for site in real_tree_imports}

    unread = [module for module in _GRAMMAR_MODULES if module not in importers]
    assert not unread, (
        f"the scan of src/solar_challenge read no import statement of {', '.join(unread)}, so "
        "test_the_scenario_grammar_imports_in_one_direction_and_imports_no_runner checks "
        "nothing of it. If a module was renamed or moved, update _GRAMMAR_STRATA with it, and "
        "docs/prds/scenario-grammar-partition.md §4.1"
    )


def test_every_grammar_import_names_a_public_name_its_module_defines(
    real_tree_src_and_test_imports: tuple[_ImportSite, ...],
) -> None:
    """Every name src/solar_challenge and tests import from a grammar module, at any scope, is a public name that module defines."""
    found = _one_spelling_violations(real_tree_src_and_test_imports, _SRC_DIR)

    violations = "\n".join(str(violation) for violation in found)
    assert not found, (
        "these import statements of src/solar_challenge and tests import a grammar name from a "
        f"module that does not define it, or an underscore name from a grammar module:\n{violations}\n"
        "Import each name from the module the report names as defining it: no grammar module "
        "re-exports a name or keeps a shim for one that moved (docs/prds/scenario-grammar-partition.md "
        "§3 decision 4, §4.2 C3). mypy --strict refuses such an import in src, since implicit "
        "re-export is off, but tests are not type-checked, so this test reads both. An underscore "
        "name is private to its module: if another module needs it, make it public in the module "
        "that defines it (decision 3)"
    )


def test_the_one_spelling_scan_reads_grammar_imports_in_src_and_tests(
    real_tree_src_and_test_imports: tuple[_ImportSite, ...],
) -> None:
    """The one-spelling scan reads a from-import of each grammar module in src and in tests, so its rule cannot pass by reading none."""
    read = {
        (site.path.parts[0], site.imported)
        for site in real_tree_src_and_test_imports
        if site.imported in _GRAMMAR_MODULES and site.names
    }

    unread = [
        f"{module} in {tree}"
        for module in _GRAMMAR_MODULES
        for tree in ("src", _TEST_SUITE)
        if (tree, module) not in read
    ]
    assert not unread, (
        f"the scan read no from-import of {', '.join(unread)}, so "
        "test_every_grammar_import_names_a_public_name_its_module_defines checks nothing of it. "
        "If the scan no longer finds src/solar_challenge or tests, point _src_and_test_import_sites "
        "at them; if a grammar module was renamed, update _GRAMMAR_STRATA"
    )


def _write_files(root: Path, files: Mapping[str, str]) -> Path:
    """Write each of *files*, keyed by its path under *root*, and return *root*."""
    for relative_path, source in files.items():
        file = root / relative_path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source, encoding="utf-8")
    return root


def _write_package(src_dir: Path, modules: dict[str, str]) -> Path:
    """Write each of *modules*, keyed by its path in the package, under src_dir/solar_challenge, and return *src_dir*."""
    _write_files(src_dir / _PACKAGE, modules)
    return src_dir


def test_a_function_local_package_import_is_reported_with_its_file_line_and_module(
    tmp_path: Path,
) -> None:
    """The report names a seeded function-local import's file, line and module: the real-tree tests pass for a scan that finds nothing."""
    src_dir = _write_package(
        tmp_path / "src",
        {
            "__init__.py": "",
            "gridservices.py": (
                "import json\n"
                "\n"
                "\n"
                "def refuse(path):\n"
                "    from solar_challenge.config import load_scenarios\n"
                "    return load_scenarios(path)\n"
            ),
        },
    )

    unlisted = _unlisted(_function_local_package_imports(_import_sites(src_dir)), frozenset())

    assert [(site.path.as_posix(), site.line, site.imported) for site in unlisted] == [
        ("src/solar_challenge/gridservices.py", 5, "solar_challenge.config")
    ]
    assert "src/solar_challenge/gridservices.py:5" in str(unlisted[0])
    assert "solar_challenge.config" in str(unlisted[0])


def test_an_allowed_pair_no_function_imports_is_reported_stale(tmp_path: Path) -> None:
    """A pair no function imports any more is reported stale: the real-tree tests pass for a report that finds nothing."""
    src_dir = _write_package(
        tmp_path / "src",
        {
            "finance.py": (
                "from solar_challenge.battery import compute_soh\n"
                "\n"
                "\n"
                "def aged(homes):\n"
                "    return compute_soh(homes)\n"
            ),
        },
    )
    pair = ("solar_challenge.finance", "solar_challenge.battery")

    assert _stale(_function_local_package_imports(_import_sites(src_dir)), {pair}) == [pair]


@pytest.mark.parametrize(
    ("module", "source", "expected"),
    [
        pytest.param(
            "finance.py",
            "from typing import TYPE_CHECKING\n"
            "\n"
            "from solar_challenge.battery import compute_soh\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    from solar_challenge.home import HomeConfig\n",
            [],
            id="module-top",
        ),
        pytest.param(
            "finance.py",
            "def f():\n    import json\n    import solar_challenge_tools\n",
            [],
            id="not-the-package",
        ),
        pytest.param(
            "finance.py",
            "class C:\n    async def f(self):\n        def g():\n            import solar_challenge.ev\n",
            [("solar_challenge.finance", "solar_challenge.ev", 4)],
            id="nested-in-a-method",
        ),
        pytest.param(
            "web/routes.py",
            "def f():\n    from .charts import x\n    from .. import fleet\n",
            [
                ("solar_challenge.web.routes", "solar_challenge.web.charts", 2),
                ("solar_challenge.web.routes", "solar_challenge.fleet", 3),
            ],
            id="relative",
        ),
        pytest.param(
            "web/routes.py",
            "def f():\n    from solar_challenge import fleet\n    from .. import fleet\n",
            [
                ("solar_challenge.web.routes", "solar_challenge.fleet", 2),
                ("solar_challenge.web.routes", "solar_challenge.fleet", 3),
            ],
            id="package-itself-absolute-and-relative",
        ),
        pytest.param(
            "web/__init__.py",
            "def create():\n    from .app import create_app\n    return create_app()\n",
            [("solar_challenge.web", "solar_challenge.web.app", 2)],
            id="relative-in-package-init",
        ),
    ],
)
def test_the_scan_finds_only_package_imports_nested_in_a_function(
    tmp_path: Path, module: str, source: str, expected: list[tuple[str, str, int]]
) -> None:
    """The scan finds an import of the package only inside a function or method, and names its module alike whether the import is absolute or relative."""
    src_dir = _write_package(tmp_path / "src", {module: source})

    found = _function_local_package_imports(_import_sites(src_dir))

    assert [(site.importer, site.imported, site.line) for site in found] == expected


def test_an_import_of_the_test_suite_is_reported_with_its_file_line_and_module(
    tmp_path: Path,
) -> None:
    """The report names a seeded import of the tests package by its file, line and module; the real-tree test passes for a scan that finds nothing."""
    src_dir = _write_package(
        tmp_path / "src",
        {
            "__init__.py": "",
            "gridservices.py": (
                "import json\n"
                "\n"
                "\n"
                "def refuse(path):\n"
                "    from tests._pyproject import load_project_table\n"
                "    return load_project_table(path)\n"
            ),
        },
    )

    found = _test_suite_imports(_import_sites(src_dir))

    assert [(site.path.as_posix(), site.line, site.imported) for site in found] == [
        ("src/solar_challenge/gridservices.py", 5, "tests._pyproject")
    ]
    assert "src/solar_challenge/gridservices.py:5" in str(found[0])
    assert "tests._pyproject" in str(found[0])


@pytest.mark.parametrize(
    ("module", "source", "expected"),
    [
        pytest.param(
            "finance.py",
            "from typing import TYPE_CHECKING\n"
            "\n"
            "import tests\n"
            "from tests._pyproject import load_project_table\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    from tests._web_app import build_test_app\n",
            [("tests", 3), ("tests._pyproject", 4), ("tests._web_app", 7)],
            id="module-top-and-type-checking",
        ),
        pytest.param(
            "finance.py",
            "def f():\n"
            "    import tests.unit.helpers as helpers\n"
            "\n"
            "\n"
            "class C:\n"
            "    async def g(self):\n"
            "        try:\n"
            "            from tests import _seeded_tmy\n"
            "        except ImportError:\n"
            "            pass\n",
            [("tests.unit.helpers", 2), ("tests", 8)],
            id="in-a-function-a-method-and-an-import-error-guard",
        ),
        pytest.param(
            "web/routes.py",
            '"""from tests import _web_app, in prose."""\n'
            "\n"
            "import tests_helpers\n"
            "from solar_challenge import tests\n"
            "from . import tests\n"
            "from .tests import fixtures\n",
            [],
            id="not-the-test-suite",
        ),
        pytest.param(
            "finance.py",
            "def f():\n    from .. import tests\n    from ..tests import fixtures\n",
            [],
            id="relative-past-the-top-package",
        ),
    ],
)
def test_the_scan_finds_imports_of_the_test_suite_at_any_scope(
    tmp_path: Path, module: str, source: str, expected: list[tuple[str, int]]
) -> None:
    """The scan finds an import of the tests package at any scope, inside an ImportError guard too, and neither a module of the package merely named tests nor a relative import that climbs past the package, which Python rejects."""
    src_dir = _write_package(tmp_path / "src", {module: source})

    found = _test_suite_imports(_import_sites(src_dir))

    assert [(site.imported, site.line) for site in found] == expected


@pytest.mark.parametrize(
    ("module", "source", "expected"),
    [
        pytest.param(
            "finance.py",
            "from solar_challenge.web.jobs import JobManager\n",
            [("solar_challenge.finance", "solar_challenge.web.jobs", 1)],
            id="module-top",
        ),
        pytest.param(
            "finance.py",
            "from typing import TYPE_CHECKING\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    from solar_challenge.web.storage import RunStorage\n",
            [("solar_challenge.finance", "solar_challenge.web.storage", 4)],
            id="type-checking",
        ),
        pytest.param(
            "home.py",
            "class Panel:\n    import solar_challenge.web.charts\n",
            [("solar_challenge.home", "solar_challenge.web.charts", 2)],
            id="class-body",
        ),
        pytest.param(
            "__init__.py",
            "from solar_challenge import web\nfrom . import web\n",
            [
                ("solar_challenge", "solar_challenge.web", 1),
                ("solar_challenge", "solar_challenge.web", 2),
            ],
            id="package-itself-absolute-and-relative",
        ),
        pytest.param(
            "cli/web.py",
            "from ..web.jobs import JobManager\n",
            [("solar_challenge.cli.web", "solar_challenge.web.jobs", 1)],
            id="relative-from-a-subpackage",
        ),
        pytest.param(
            "cli/web.py",
            "def start():\n    from solar_challenge.web import create_app\n",
            [],
            id="inside-a-function",
        ),
        pytest.param(
            "web/routes.py",
            "from solar_challenge.web.charts import x\nfrom . import jobs\n",
            [],
            id="within-the-web-subpackage",
        ),
        pytest.param(
            "cli/main.py",
            "from solar_challenge.cli import web as web_app\nimport solar_challenge.web_tools\n",
            [],
            id="not-the-web-subpackage",
        ),
    ],
)
def test_the_scan_finds_module_top_imports_into_the_web_subpackage(
    tmp_path: Path, module: str, source: str, expected: list[tuple[str, str, int]]
) -> None:
    """The scan finds an import of the web subpackage from outside it at module top and in a class body, which run when the module is imported, and in a TYPE_CHECKING block, which never runs but which the scan reads like any other statement: a module outside the subpackage should not need the subpackage even for its annotations. It finds none inside a function, which INV-5's allow-list governs, nor one within the subpackage, nor one of a module merely named web."""
    src_dir = _write_package(tmp_path / "src", {module: source})

    found = _module_top_imports_into_the_web_subpackage(_import_sites(src_dir))

    assert [(site.importer, site.imported, site.line) for site in found] == expected


@pytest.mark.parametrize(
    ("module", "source", "expected"),
    [
        pytest.param(
            "web/database.py",
            "import sqlite3\n"
            "\n"
            "from solar_challenge.web.storage import RunRecord\n"
            "import solar_challenge.web.presets as presets\n",
            [("solar_challenge.web.storage", 3), ("solar_challenge.web.presets", 4)],
            id="module-top",
        ),
        pytest.param(
            "web/database.py",
            "from .chat_messages import ChatRole\nfrom . import presets\n",
            [("solar_challenge.web.chat_messages", 1), ("solar_challenge.web.presets", 2)],
            id="relative",
        ),
        pytest.param(
            "web/database.py",
            "import solar_challenge.web\nfrom solar_challenge import web\nfrom .. import web\n",
            [("solar_challenge.web", 1), ("solar_challenge.web", 2), ("solar_challenge.web", 3)],
            id="the-web-package-itself",
        ),
        pytest.param(
            "web/database.py",
            "from typing import TYPE_CHECKING\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    from solar_challenge.web.stored_runs import RunType\n",
            [("solar_challenge.web.stored_runs", 4)],
            id="type-checking",
        ),
        pytest.param(
            "web/database.py",
            "def rebuild(conn):\n"
            "    from solar_challenge.web.schema import MIGRATIONS\n"
            "\n"
            "\n"
            "try:\n"
            "    from .storage import RunStorage\n"
            "except ImportError:\n"
            "    RunStorage = None\n",
            [("solar_challenge.web.schema", 2), ("solar_challenge.web.storage", 6)],
            id="in-a-function-and-an-import-error-guard",
        ),
        pytest.param(
            "web/database.py",
            "import sqlite3\n"
            "from solar_challenge.errors import ConfigurationError\n"
            "from .. import fleet\n"
            "import solar_challenge.web_tools\n",
            [],
            id="not-the-web-subpackage",
        ),
        pytest.param(
            "web/storage.py",
            "from solar_challenge.web.database import Database\nfrom .stored_runs import RunType\n",
            [],
            id="another-web-module",
        ),
    ],
)
def test_the_scan_finds_web_database_imports_of_the_web_subpackage_at_any_scope(
    tmp_path: Path, module: str, source: str, expected: list[tuple[str, int]]
) -> None:
    """The scan finds an import of the web subpackage in web/database.py at any scope (module top, a TYPE_CHECKING block, a function, an ImportError guard), absolute or relative, the web package itself included. It finds none of a package module outside the subpackage, none of a module merely named web_tools, and none that another web module makes."""
    src_dir = _write_package(tmp_path / "src", {module: source})

    found = _imports_by(_WEB_DATABASE, WEB_SUBPACKAGE, _import_sites(src_dir))

    assert [(site.imported, site.line) for site in found] == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "from solar_challenge.errors import ConfigurationError\n"
            "from .. import config\n"
            "import solar_challenge\n",
            [("solar_challenge.errors", 1), ("solar_challenge.config", 2), ("solar_challenge", 3)],
            id="the-package-outside-the-web-subpackage",
        ),
        pytest.param(
            "def read(content):\n    from .stored_runs import StoredRunUnreadable\n",
            [("solar_challenge.web.stored_runs", 2)],
            id="the-web-subpackage-in-a-function",
        ),
        pytest.param(
            "import functools\n\nimport pandas as pd\nimport solar_challenge_tools\n",
            [],
            id="not-the-package",
        ),
    ],
)
def test_the_scan_finds_web_field_tree_imports_of_the_package_at_any_scope(
    tmp_path: Path, source: str, expected: list[tuple[str, int]]
) -> None:
    """The scan finds an import of any module of the package in web/field_tree.py, at any scope, absolute or relative, the package itself included: outside the web subpackage too, where web/database.py's rule finds none. It finds none of a module outside the package."""
    src_dir = _write_package(tmp_path / "src", {"web/field_tree.py": source})

    found = _imports_by(_WEB_FIELD_TREE, _PACKAGE, _import_sites(src_dir))

    assert [(site.imported, site.line) for site in found] == expected


def test_an_upward_grammar_import_and_a_runner_import_are_reported_with_their_file_line_and_rule(
    tmp_path: Path,
) -> None:
    """One scan reports a seeded function-local import of config in scenario_blocks.py and a seeded import of simulate_home in fleet_distribution.py, each by its file, line and the rule it breaks: the real-tree test passes for a scan that finds nothing."""
    src_dir = _write_package(
        tmp_path / "src",
        {
            "scenario_blocks.py": (
                "def read(path):\n"
                "    from solar_challenge.config import load_config\n"
                "    return load_config(path)\n"
            ),
            "fleet_distribution.py": (
                "from solar_challenge.scenario_blocks import child_path\n"
                "from solar_challenge.home import simulate_home\n"
            ),
        },
    )

    found = _grammar_layering_violations(_import_sites(src_dir))

    assert [(violation.path.as_posix(), violation.line, violation.rule) for violation in found] == [
        ("src/solar_challenge/fleet_distribution.py", 2, _GrammarRule.NO_RUNNER),
        ("src/solar_challenge/scenario_blocks.py", 2, _GrammarRule.IMPORT_DIRECTION),
    ]
    runner, upward = (str(violation) for violation in found)
    assert "src/solar_challenge/fleet_distribution.py:2" in runner
    assert "simulate_home" in runner
    assert _GrammarRule.NO_RUNNER.value in runner
    assert "src/solar_challenge/scenario_blocks.py:2" in upward
    assert "solar_challenge.config" in upward
    assert _GrammarRule.IMPORT_DIRECTION.value in upward


@pytest.mark.parametrize(
    ("module", "source", "expected"),
    [
        pytest.param(
            "scenario_blocks.py",
            "from solar_challenge.config import load_config\n"
            "import solar_challenge.fleet_distribution\n",
            [
                ("solar_challenge.config", 1, _GrammarRule.IMPORT_DIRECTION),
                ("solar_challenge.fleet_distribution", 2, _GrammarRule.IMPORT_DIRECTION),
            ],
            id="module-top-absolute",
        ),
        pytest.param(
            "scenario_blocks.py",
            "from .config import load_config\nfrom . import fleet_distribution\n",
            [
                ("solar_challenge.config", 1, _GrammarRule.IMPORT_DIRECTION),
                ("solar_challenge.fleet_distribution", 2, _GrammarRule.IMPORT_DIRECTION),
            ],
            id="relative",
        ),
        pytest.param(
            "scenario_blocks.py",
            "from solar_challenge import config\n",
            [("solar_challenge.config", 1, _GrammarRule.IMPORT_DIRECTION)],
            id="the-package-form",
        ),
        pytest.param(
            "scenario_blocks.py",
            "from typing import TYPE_CHECKING\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    from solar_challenge.fleet_distribution import SweepSpec\n",
            [("solar_challenge.fleet_distribution", 4, _GrammarRule.IMPORT_DIRECTION)],
            id="type-checking",
        ),
        pytest.param(
            "scenario_blocks.py",
            "def parse(data):\n"
            "    from solar_challenge.config import ScenarioConfig\n"
            "\n"
            "\n"
            "try:\n"
            "    from .fleet_distribution import parse_fleet_distribution_config\n"
            "except ImportError:\n"
            "    parse_fleet_distribution_config = None\n",
            [
                ("solar_challenge.config", 2, _GrammarRule.IMPORT_DIRECTION),
                ("solar_challenge.fleet_distribution", 6, _GrammarRule.IMPORT_DIRECTION),
            ],
            id="in-a-function-and-an-import-error-guard",
        ),
        pytest.param(
            "scenario_blocks.py",
            "from solar_challenge.errors import ConfigurationError\n"
            "from .home import HomeConfig\n"
            "import solar_challenge.config_tools\n",
            [],
            id="not-the-grammar-above",
        ),
        pytest.param(
            "config.py",
            "from solar_challenge.scenario_blocks import child_path\n",
            [],
            id="another-module",
        ),
        pytest.param(
            "fleet_distribution.py",
            "from solar_challenge.config import load_config\n"
            "from . import config\n"
            "\n"
            "\n"
            "def read(path):\n"
            "    from .config import load_fleet_config\n",
            [
                ("solar_challenge.config", 1, _GrammarRule.IMPORT_DIRECTION),
                ("solar_challenge.config", 2, _GrammarRule.IMPORT_DIRECTION),
                ("solar_challenge.config", 6, _GrammarRule.IMPORT_DIRECTION),
            ],
            id="fleet-distribution-imports-config",
        ),
        pytest.param(
            "errors.py",
            "from solar_challenge.scenario_blocks import block_label\n",
            [("solar_challenge.scenario_blocks", 1, _GrammarRule.IMPORT_DIRECTION)],
            id="a-leaf-imports-scenario-blocks",
        ),
        pytest.param(
            "number_fields.py",
            "from typing import TYPE_CHECKING\n"
            "\n"
            "if TYPE_CHECKING:\n"
            "    from solar_challenge.fleet_distribution import SweepSpec\n",
            [("solar_challenge.fleet_distribution", 4, _GrammarRule.IMPORT_DIRECTION)],
            id="a-leaf-imports-fleet-distribution-under-type-checking",
        ),
        pytest.param(
            "fleet_distribution.py",
            "from solar_challenge.errors import ConfigurationError\n"
            "from solar_challenge.scenario_blocks import child_path\n",
            [],
            id="fleet-distribution-imports-below-it",
        ),
        pytest.param(
            "config.py",
            "from solar_challenge.fleet_distribution import SweepSpec\n"
            "from .scenario_blocks import parse_home_block\n",
            [],
            id="config-imports-below-it",
        ),
        pytest.param(
            "config.py",
            "def run(config):\n    from solar_challenge.fleet import simulate_fleet as run\n",
            [("simulate_fleet", 2, _GrammarRule.NO_RUNNER)],
            id="a-runner-in-a-function-named-by-its-name-not-its-alias",
        ),
        pytest.param(
            "scenario_blocks.py",
            "from .home import simulate_home\n",
            [("simulate_home", 1, _GrammarRule.NO_RUNNER)],
            id="a-runner-imported-relatively",
        ),
        pytest.param(
            "fleet_distribution.py",
            "from solar_challenge.fleet import fleet_home_seed\n",
            [],
            id="not-a-runner",
        ),
        pytest.param(
            "cli/home.py",
            "from solar_challenge.home import simulate_home\n",
            [],
            id="a-runner-outside-the-grammar",
        ),
        pytest.param(
            "fleet_distribution.py",
            "from simulate_tools import simulate_x\n",
            [],
            id="a-runner-outside-the-package",
        ),
    ],
)
def test_the_scan_finds_grammar_imports_against_the_direction_or_of_a_runner_at_any_scope(
    tmp_path: Path, module: str, source: str, expected: list[tuple[str, int, _GrammarRule]]
) -> None:
    """The scan finds, at any scope (module top, a TYPE_CHECKING block, a function, an ImportError guard), absolute, relative or through the package, an import against the grammar's direction, from a leaf or a grammar module of a module of a stratum above its own, and a grammar module's import of a simulate_* name from a module of the package, named by the name it imports, not its alias. It finds none of a module below the importer's stratum or merely named config_tools, none of a name that is no runner, and none of a runner that a module outside the grammar imports or that a module outside the package defines."""
    src_dir = _write_package(tmp_path / "src", {module: source})

    found = _grammar_layering_violations(_import_sites(src_dir))

    assert [(violation.subject, violation.line, violation.rule) for violation in found] == expected


#: A package of the three grammar modules, scenario_blocks defining parse_home_block and config
#: importing it, with an empty tests package: the root the one-spelling tests seed.
_ONE_SPELLING_ROOT: Mapping[str, str] = {
    "src/solar_challenge/__init__.py": "",
    "src/solar_challenge/scenario_blocks.py": "def parse_home_block(data):\n    return data\n",
    "src/solar_challenge/fleet_distribution.py": "",
    "src/solar_challenge/config.py": "from solar_challenge.scenario_blocks import parse_home_block\n",
    "tests/__init__.py": "",
    "tests/unit/__init__.py": "",
}


def _one_spelling_violations_under(root: Path) -> list[_GrammarViolation]:
    """Return the one-spelling violations of the src/solar_challenge and tests trees under *root*."""
    return _one_spelling_violations(_src_and_test_import_sites(root), root / "src")


def test_a_grammar_name_imported_from_a_module_that_does_not_define_it_is_reported_naming_its_definer(
    tmp_path: Path,
) -> None:
    """A seeded test module importing parse_home_block from config, which only imports it, is reported by its file, line and rule, naming the module that defines it; config's own import from scenario_blocks is not: the real-tree test passes for a scan that finds nothing."""
    root = _write_files(
        tmp_path,
        {
            **_ONE_SPELLING_ROOT,
            "tests/unit/test_homes.py": "import json\nfrom solar_challenge.config import parse_home_block\n",
        },
    )

    found = _one_spelling_violations_under(root)

    assert [(violation.path.as_posix(), violation.line, violation.rule) for violation in found] == [
        ("tests/unit/test_homes.py", 2, _GrammarRule.ONE_SPELLING)
    ]
    report = str(found[0])
    assert "parse_home_block" in report
    assert "solar_challenge.config" in report
    assert "solar_challenge.scenario_blocks" in report


def test_a_grammar_name_no_module_defines_is_reported_saying_so(tmp_path: Path) -> None:
    """A name imported from a grammar module that no module of the package defines is reported saying so, not naming a definer."""
    root = _write_files(
        tmp_path,
        {**_ONE_SPELLING_ROOT, "tests/unit/test_missing.py": "from solar_challenge.config import Missing\n"},
    )

    [violation] = _one_spelling_violations_under(root)

    assert violation.rule is _GrammarRule.ONE_SPELLING
    assert "Missing" in str(violation)
    assert "no module of the package defines it" in str(violation)


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        pytest.param(
            {
                "src/solar_challenge/fleet_distribution.py": "class _DistributionSampler:\n    pass\n",
                "tests/unit/test_sampler.py": "from solar_challenge.fleet_distribution import _DistributionSampler\n",
            },
            [("tests/unit/test_sampler.py", 1, _GrammarRule.NO_PRIVATE_NAME)],
            id="an-underscore-name-its-module-defines-in-a-test",
        ),
        pytest.param(
            {
                "src/solar_challenge/scenario_blocks.py": (
                    "def parse_home_block(data):\n    return data\n\n\ndef _read_name(block):\n    return block\n"
                ),
                "src/solar_challenge/fleet_distribution.py": (
                    "def read(block):\n"
                    "    from solar_challenge.scenario_blocks import _read_name\n"
                    "    return _read_name(block)\n"
                ),
            },
            [("src/solar_challenge/fleet_distribution.py", 2, _GrammarRule.NO_PRIVATE_NAME)],
            id="an-underscore-name-in-a-function-of-src",
        ),
        pytest.param(
            {
                "src/solar_challenge/cli/__init__.py": "",
                "src/solar_challenge/cli/home.py": "from ..config import parse_home_block\n",
            },
            [("src/solar_challenge/cli/home.py", 1, _GrammarRule.ONE_SPELLING)],
            id="relative-from-a-subpackage",
        ),
        pytest.param(
            {"tests/unit/test_missing.py": "from solar_challenge.config import Missing\n"},
            [("tests/unit/test_missing.py", 1, _GrammarRule.ONE_SPELLING)],
            id="a-name-no-module-defines",
        ),
        pytest.param(
            {
                "src/solar_challenge/config.py": "def load_config(path):\n    return path\n",
                "tests/unit/test_load.py": "from solar_challenge.config import load_config\n",
            },
            [],
            id="a-name-its-module-defines",
        ),
        pytest.param(
            {
                "src/solar_challenge/config.py": (
                    "try:\n"
                    "    import yaml\n"
                    "except ImportError:\n"
                    "    LOADER = None\n"
                    "else:\n"
                    "    LOADER = yaml.SafeLoader\n"
                    "finally:\n"
                    "    READ_MODE: str = 'r'\n"
                    "\n"
                    "if LOADER is not None:\n"
                    "    def load_config(path):\n"
                    "        return path\n"
                ),
                "tests/unit/test_load.py": "from solar_challenge.config import LOADER, READ_MODE, load_config\n",
            },
            [],
            id="names-defined-in-a-top-level-if-or-try",
        ),
        pytest.param(
            {"tests/unit/test_config_module.py": "from solar_challenge import config\n"},
            [],
            id="a-module-not-a-name",
        ),
        pytest.param(
            {
                "src/solar_challenge/home.py": "from solar_challenge.load import HomeConfig\n",
                "tests/unit/test_home.py": "from solar_challenge.home import HomeConfig\n",
            },
            [],
            id="not-a-grammar-module",
        ),
    ],
)
def test_the_one_spelling_scan_reads_src_and_tests_at_any_scope(
    tmp_path: Path, files: dict[str, str], expected: list[tuple[str, int, _GrammarRule]]
) -> None:
    """The scan reads the from-imports of src and tests at any scope, a relative one resolved, and reports an underscore name imported from a grammar module, even one it defines, and a public name imported from a grammar module that does not define it, at top level or in a top-level if or try. It reports no import of a module and none from a module outside the grammar."""
    root = _write_files(tmp_path, {**_ONE_SPELLING_ROOT, **files})

    found = _one_spelling_violations_under(root)

    assert [(violation.path.as_posix(), violation.line, violation.rule) for violation in found] == expected

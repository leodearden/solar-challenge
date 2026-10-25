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

All four read import statements only: the lazy loader in solar_challenge/__init__.py
(`__getattr__`, which calls importlib.import_module) is pinned by
tests/unit/test_init_lazy_surface.py.
"""

import ast
from collections.abc import Collection, Iterable, Iterator
from dataclasses import astuple, dataclass
from pathlib import Path

import pytest

from tests._declared_dependencies import WEB_SUBPACKAGE

_PACKAGE = "solar_challenge"
_TEST_SUITE = "tests"
_WEB_DATABASE = f"{WEB_SUBPACKAGE}.database"
_SRC_DIR = Path(__file__).resolve().parents[2] / "src"


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
        "tests/unit/test_init_lazy_surface.py::test_import_is_pvlib_free)"
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
    """One module an import statement of the package imports: the importing and imported modules, the statement's file and line, and whether it sits inside a function."""

    importer: str
    imported: str
    path: Path
    line: int
    in_function: bool

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line} imports {self.imported}"


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


def _imported_modules(
    node: ast.Import | ast.ImportFrom, importer: str, is_package: bool
) -> list[str]:
    """Return the dotted names of the modules *node* imports; a from-import with no module or of the top-level package names each alias as a module of it, however it is spelled."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    from_module = _from_module(node, importer, is_package)
    if node.module is None or from_module == _PACKAGE:
        return [f"{from_module}.{alias.name}" for alias in node.names]
    return [from_module]


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


def _import_sites(src_dir: Path) -> list[_ImportSite]:
    """Return a site for every module an import statement of the package under *src_dir* imports, at any scope, in path then line order."""
    sites: list[_ImportSite] = []
    for source in sorted((src_dir / _PACKAGE).rglob("*.py")):
        importer = _module_name(source, src_dir)
        path = source.relative_to(src_dir.parent)
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node, in_function in _import_statements(tree):
            for imported in _imported_modules(node, importer, source.name == "__init__.py"):
                sites.append(_ImportSite(importer, imported, path, node.lineno, in_function))
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


def _web_database_imports_of_the_web_subpackage(sites: Iterable[_ImportSite]) -> list[_ImportSite]:
    """Return the *sites* at which web/database.py imports a module of the web subpackage, at any scope."""
    return [
        site
        for site in sites
        if site.importer == _WEB_DATABASE and _in_package(site.imported, WEB_SUBPACKAGE)
    ]


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
    """web/database.py imports no module of the web subpackage, at any scope: docs/prds/run-store-one-owner.md §4 makes it the leaf of the persistence stratum, which every table owner and web/schema.py import."""
    found = _web_database_imports_of_the_web_subpackage(real_tree_imports)

    sites = "\n".join(str(site) for site in found)
    assert not found, (
        "these import statements of web/database.py import a module of the web subpackage:"
        f"\n{sites}\n"
        "docs/prds/run-store-one-owner.md §4 makes database.py the leaf of the persistence "
        "stratum: it imports no solar_challenge.web module. Every table owner and web/schema.py "
        "import it (§3.1), so a web import in it closes an import cycle or makes the bottom of "
        "the stratum depend on a module above it. The rule holds at any scope. An import inside "
        "a function counts, and an ALLOWED_FUNCTION_LOCAL_IMPORTS entry does not exempt it; "
        "neither does one in a TYPE_CHECKING block or an ImportError guard. Import a table "
        "owner's names from that owner, never through database.py; pass what database.py needs "
        "in as an argument, as check_one_of takes each owner's values; or move the code into "
        "database.py if it belongs to the connection policy or the table mechanism"
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


def _write_package(src_dir: Path, modules: dict[str, str]) -> Path:
    """Write each of *modules*, keyed by its path in the package, under src_dir/solar_challenge, and return *src_dir*."""
    for relative_path, source in modules.items():
        module = src_dir / _PACKAGE / relative_path
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text(source, encoding="utf-8")
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

    found = _web_database_imports_of_the_web_subpackage(_import_sites(src_dir))

    assert [(site.imported, site.line) for site in found] == expected

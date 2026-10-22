# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import-structure contract test (INV-5).

No import statement inside a function of solar_challenge names another of its modules,
except for the (importing module, imported module) pairs ALLOWED_FUNCTION_LOCAL_IMPORTS
lists. Each pair carries a Permanent reason, the documented contract that requires the
laziness, or a Transitional one, the task or program stream that removes the import.
The check runs both ways, so the change that removes a pair's last such import deletes
its entry. It reads import statements only: the lazy loader in solar_challenge/__init__.py
(`__getattr__`, which calls importlib.import_module) is pinned by
tests/unit/test_init_lazy_surface.py. docs/prds/errors-leaf.md §7 measured and classified
the list.
"""

import ast
from collections.abc import Collection, Iterable, Iterator
from dataclasses import astuple, dataclass
from pathlib import Path

import pytest

_PACKAGE = "solar_challenge"
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
    "inside `web start`"
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
    ("solar_challenge.cli.web", "solar_challenge.web.jobs"): _CLI_WITHOUT_THE_WEB_EXTRA,
    ("solar_challenge.cli.web", "solar_challenge.web.store_lock"): _CLI_WITHOUT_THE_WEB_EXTRA,
    ("solar_challenge.web", "solar_challenge.web.app"): Permanent(
        "the optional web extra: importing any web submodule runs web/__init__.py, and the web "
        "submodules that need no Flask import without the extra "
        "(tests/unit/test_conftests_need_no_web_extra.py) only while create_app defers web.app, "
        "which imports Flask"
    ),

    ("solar_challenge.finance", "solar_challenge.battery"): _FINANCE_PARTITION,
    ("solar_challenge.finance", "solar_challenge.fleet"): _FINANCE_PARTITION,
    ("solar_challenge.finance", "solar_challenge.gridservices"): Transitional("task 801 (S9 α)"),
    ("solar_challenge.finance", "solar_challenge.home"): _FINANCE_PARTITION,
    ("solar_challenge.finance", "solar_challenge.pv"): _FINANCE_PARTITION,
    ("solar_challenge.load", "solar_challenge.ev"): Transitional(
        "program stream S12, load composition"
    ),
}


@dataclass(frozen=True)
class _FunctionLocalImport:
    """One import of a module of the package inside a function: the importing and imported modules, and the import's file and line."""

    importer: str
    imported: str
    path: Path
    line: int

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line} imports {self.imported} inside a function"


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


def _imports_nested_in_functions(
    node: ast.AST, in_function: bool = False
) -> Iterator[ast.Import | ast.ImportFrom]:
    """Yield, once each, the imports under *node* that sit inside a function or method."""
    for child in ast.iter_child_nodes(node):
        if in_function and isinstance(child, (ast.Import, ast.ImportFrom)):
            yield child
        yield from _imports_nested_in_functions(
            child, in_function or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        )


def _function_local_package_imports(src_dir: Path) -> list[_FunctionLocalImport]:
    """Return every import of the package's modules inside a function of the package under *src_dir*, in path then line order."""
    found: list[_FunctionLocalImport] = []
    for source in sorted((src_dir / _PACKAGE).rglob("*.py")):
        importer = _module_name(source, src_dir)
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in _imports_nested_in_functions(tree):
            for imported in _imported_modules(node, importer, source.name == "__init__.py"):
                if imported == _PACKAGE or imported.startswith(f"{_PACKAGE}."):
                    found.append(
                        _FunctionLocalImport(
                            importer, imported, source.relative_to(src_dir.parent), node.lineno
                        )
                    )
    return found


def _unlisted(
    found: Iterable[_FunctionLocalImport], allowed: Collection[tuple[str, str]]
) -> list[_FunctionLocalImport]:
    """Return the *found* sites whose (importing module, imported module) pair is not in *allowed*."""
    return [site for site in found if (site.importer, site.imported) not in allowed]


def _stale(
    found: Iterable[_FunctionLocalImport], allowed: Collection[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Return the sorted pairs of *allowed* that no *found* site imports."""
    imported = {(site.importer, site.imported) for site in found}
    return sorted(set(allowed) - imported)


@pytest.fixture(scope="module")
def real_tree_imports() -> tuple[_FunctionLocalImport, ...]:
    """The function-local package imports of src/solar_challenge, scanned once for the module's two real-tree tests."""
    return tuple(_function_local_package_imports(_SRC_DIR))


def test_every_function_local_package_import_is_allowed(
    real_tree_imports: tuple[_FunctionLocalImport, ...],
) -> None:
    """Every import of a module of the package inside a function is of a pair ALLOWED_FUNCTION_LOCAL_IMPORTS lists."""
    unlisted = _unlisted(real_tree_imports, ALLOWED_FUNCTION_LOCAL_IMPORTS)

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
    real_tree_imports: tuple[_FunctionLocalImport, ...],
) -> None:
    """Every pair ALLOWED_FUNCTION_LOCAL_IMPORTS lists is still imported inside a function of the package."""
    stale = _stale(real_tree_imports, ALLOWED_FUNCTION_LOCAL_IMPORTS)

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

    unlisted = _unlisted(_function_local_package_imports(src_dir), frozenset())

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

    assert _stale(_function_local_package_imports(src_dir), {pair}) == [pair]


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

    found = _function_local_package_imports(src_dir)

    assert [(site.importer, site.imported, site.line) for site in found] == expected

# SPDX-License-Identifier: AGPL-3.0-or-later
"""The layers of the surface-forms helper, whose modules are tests/_surface_forms*.py.

LAYERS lists the helper's modules bottom first. Of the helper, each imports only the
modules listed before it, and only at module level, so each reads alone: no reach-back,
no cycle, and no import placed in a function to break one.
"""

import ast
import importlib.util
from collections.abc import Iterator
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]

LAYERS = ("_surface_forms_module_lookup", "_surface_forms")


def _helper_imports(tree: ast.Module) -> Iterator[tuple[ast.Import | ast.ImportFrom, str]]:
    """Each import statement anywhere in *tree* that names a module of the helper, with that module's stem."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = importlib.util.resolve_name("." * node.level + (node.module or ""), "tests")
            names = [base, *(f"{base}.{alias.name}" for alias in node.names)]
        else:
            continue
        for name in names:
            package, _, stem = name.rpartition(".")
            if package == "tests" and stem in LAYERS:
                yield node, stem


def test_every_module_of_the_helper_is_a_layer() -> None:
    modules = sorted(path.stem for path in _TESTS.glob("_surface_forms*.py"))

    assert modules == sorted(LAYERS), (
        "LAYERS must list each module of the helper, tests/_surface_forms*.py, once and "
        "nothing else: put a new module of the helper into LAYERS above every module it imports"
    )


def test_each_layer_imports_of_the_helper_only_the_layers_below_it_at_module_level() -> None:
    violations: list[str] = []
    for index, stem in enumerate(LAYERS):
        tree = ast.parse((_TESTS / f"{stem}.py").read_bytes())
        for statement, imported in _helper_imports(tree):
            site = f"tests/{stem}.py:{statement.lineno} imports tests.{imported}"
            if LAYERS.index(imported) >= index:
                violations.append(f"{site}, which is not below it")
            elif statement not in tree.body:
                violations.append(f"{site} below module level")

    assert violations == [], (
        "Of the helper, each module may import only the modules below it in LAYERS, and only "
        "at module top. Move a name two layers need down to the lowest layer that uses it, "
        "and import it at module top:\n" + "\n".join(violations)
    )

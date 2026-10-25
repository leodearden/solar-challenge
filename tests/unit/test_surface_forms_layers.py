# SPDX-License-Identifier: AGPL-3.0-or-later
"""The layers of the surface-forms helper, whose modules are tests/_surface_forms*.py.

LAYERS lists the helper's modules bottom first. Of the helper, each imports only the
modules listed before it, and only at module level, so each reads alone: no reach-back,
no cycle, and no import placed in a function to break one. Its docstrings likewise name,
of the other modules, only public names of those below it.
"""

import ast
import importlib.util
import re
from collections.abc import Collection, Iterator
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]

LAYERS = ("_surface_forms_module_lookup", "_surface_forms_signatures", "_surface_forms")

_DOCUMENTED = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


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


def _top_level_names(tree: ast.Module) -> set[str]:
    """The names *tree*'s module-level statements define: each function's, class's and assigned name."""
    names: set[str] = set()
    for statement in tree.body:
        match statement:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                names.add(name)
            case ast.Assign(targets=targets):
                names.update(target.id for target in targets if isinstance(target, ast.Name))
            case ast.AnnAssign(target=ast.Name(id=name)):
                names.add(name)
    return names


def _docstring_mentions(tree: ast.Module, names: Collection[str]) -> Iterator[tuple[int, str]]:
    """Each of *names* that a docstring in *tree* mentions, the module's or a function's or class's at any depth, with the line of the mention."""
    for node in ast.walk(tree):
        if isinstance(node, _DOCUMENTED) and (docstring := ast.get_docstring(node, clean=False)):
            for line, text in enumerate(docstring.splitlines(), start=node.body[0].lineno):
                yield from ((line, word) for word in _IDENTIFIER.findall(text) if word in names)


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


def test_the_docstrings_of_each_layer_name_of_the_other_layers_only_public_names_below_it() -> None:
    trees = {stem: ast.parse((_TESTS / f"{stem}.py").read_bytes()) for stem in LAYERS}
    owners = {name: stem for stem, tree in trees.items() for name in _top_level_names(tree)}
    violations: list[str] = []
    for index, stem in enumerate(LAYERS):
        for line, name in _docstring_mentions(trees[stem], owners.keys()):
            owner = owners[name]
            site = f"tests/{stem}.py:{line} names {name} of tests.{owner}"
            if LAYERS.index(owner) > index:
                violations.append(f"{site}, which is not below it")
            elif LAYERS.index(owner) < index and name.startswith("_"):
                violations.append(f"{site}, a private name")

    assert violations == [], (
        "Of the helper, each module's docstrings may name, of the other modules, only public "
        "names of those below it in LAYERS. Cite the public name whose docstring points to "
        "the private one, or state the rule in this module's own words:\n"
        + "\n".join(violations)
    )

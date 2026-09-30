"""Guards the dashboard's Jinja macro libraries against dead macros and against
templates whose imports do not match the macros they call.
"""

import pytest
pytest.importorskip("jinja2")
from jinja2 import Environment, PackageLoader, nodes

_LOADER = PackageLoader("solar_challenge.web", "templates")
_ENV = Environment(loader=_LOADER)

MACRO_LIBRARIES = ["components/macros.html"]


def _parse_templates() -> dict[str, nodes.Template]:
    trees: dict[str, nodes.Template] = {}
    for name in _ENV.list_templates(extensions=["html"]):
        source, _, _ = _LOADER.get_source(_ENV, name)
        trees[name] = _ENV.parse(source, name=name)
    return trees


def _imported_pairs(statement: nodes.FromImport) -> list[tuple[str, str]]:
    """(macro, local name) for each name one ``{% from %}`` statement imports."""
    return [
        (entry, entry) if isinstance(entry, str) else entry
        for entry in statement.names
    ]


def _imports_from(tree: nodes.Template, library: str) -> list[tuple[str, str]]:
    """(macro, local name) for each name the template imports from ``library``."""
    return [
        pair
        for statement in tree.find_all(nodes.FromImport)
        if isinstance(statement.template, nodes.Const)
        and statement.template.value == library
        for pair in _imported_pairs(statement)
    ]


def _called_names(tree: nodes.Template) -> set[str]:
    """Names used as a call target, by ``{{ m(...) }}`` and ``{% call m(...) %}`` alike."""
    return {
        call.node.name
        for call in tree.find_all(nodes.Call)
        if isinstance(call.node, nodes.Name)
    }


def _defined_macros(tree: nodes.Template) -> set[str]:
    return {macro.name for macro in tree.find_all(nodes.Macro)}


def _bound_names(tree: nodes.Template) -> set[str]:
    """Names the template binds itself: every ``{% from %}`` import (any library) and its own macros."""
    imported = {
        local
        for statement in tree.find_all(nodes.FromImport)
        for _, local in _imported_pairs(statement)
    }
    return imported | _defined_macros(tree)


@pytest.mark.parametrize("library", MACRO_LIBRARIES)
def test_templates_import_exactly_the_library_macros_they_call(library: str) -> None:
    templates = _parse_templates()
    defined = _defined_macros(templates[library])

    mismatches: dict[str, dict[str, list[str]]] = {}
    for name, tree in templates.items():
        called = _called_names(tree)
        unused = sorted(
            local for _, local in _imports_from(tree, library) if local not in called
        )
        missing = sorted((called & defined) - _bound_names(tree))
        if unused or missing:
            mismatches[name] = {
                "imported but never called": unused,
                "called but not imported": missing,
            }

    assert mismatches == {}

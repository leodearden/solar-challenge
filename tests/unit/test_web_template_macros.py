"""Guards the dashboard's Jinja macro libraries against dead macros and against
templates whose imports do not match the macros they call.
"""

import pytest
pytest.importorskip("jinja2")
from jinja2 import BaseLoader, DictLoader, Environment, PackageLoader, nodes

MACRO_LIBRARIES = ["components/macros.html", "components/icons.html"]


def _parsed_templates(loader: BaseLoader) -> dict[str, nodes.Template]:
    """Every HTML template the loader holds, parsed."""
    environment = Environment(loader=loader)
    trees: dict[str, nodes.Template] = {}
    for name in environment.list_templates(extensions=["html"]):
        source, _, _ = loader.get_source(environment, name)
        trees[name] = environment.parse(source, name=name)
    return trees


@pytest.fixture(scope="module")
def templates() -> dict[str, nodes.Template]:
    """Every dashboard template parsed once, shared by all the checks below."""
    return _parsed_templates(PackageLoader("solar_challenge.web", "templates"))


def _imported_pairs(statement: nodes.FromImport) -> list[tuple[str, str]]:
    """(macro, local name) for each name one ``{% from %}`` statement imports."""
    return [
        (entry, entry) if isinstance(entry, str) else entry
        for entry in statement.names
    ]


def _imports_library(statement: nodes.FromImport | nodes.Import, library: str) -> bool:
    return (
        isinstance(statement.template, nodes.Const)
        and statement.template.value == library
    )


def _imports_from(tree: nodes.Template, library: str) -> list[tuple[str, str]]:
    """(macro, local name) for each name the template imports from ``library``."""
    return [
        pair
        for statement in tree.find_all(nodes.FromImport)
        if _imports_library(statement, library)
        for pair in _imported_pairs(statement)
    ]


def _namespace_aliases(tree: nodes.Template, library: str) -> list[str]:
    """Aliases the template binds with ``{% import "<library>" as alias %}``."""
    return [
        statement.target
        for statement in tree.find_all(nodes.Import)
        if _imports_library(statement, library)
    ]


def _called_names(tree: nodes.Template) -> set[str]:
    """Names used as a call target, by ``{{ m(...) }}`` and ``{% call m(...) %}`` alike."""
    return {
        call.node.name
        for call in tree.find_all(nodes.Call)
        if isinstance(call.node, nodes.Name)
    }


def _called_library_macros(tree: nodes.Template, library: str) -> set[str]:
    """Macros of ``library`` the template imports by name and calls."""
    called = _called_names(tree)
    return {macro for macro, local in _imports_from(tree, library) if local in called}


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
def test_templates_import_library_macros_by_name(
    templates: dict[str, nodes.Template], library: str
) -> None:
    namespace_importers = {
        name: aliases
        for name, tree in templates.items()
        if (aliases := _namespace_aliases(tree, library))
    }

    assert namespace_importers == {}, (
        f"{library} macros must be imported with {{% from %}}; "
        "the checks here cannot follow a {% import %} alias"
    )


@pytest.mark.parametrize("library", MACRO_LIBRARIES)
def test_templates_import_exactly_the_library_macros_they_call(
    templates: dict[str, nodes.Template], library: str
) -> None:
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


def test_a_macro_a_reached_macro_calls_is_reached_but_one_only_an_unreached_macro_or_itself_calls_is_not() -> None:
    templates = _parsed_templates(
        DictLoader(
            {
                "lib.html": (
                    "{% macro used() %}{{ helper() }}{% endmacro %}"
                    "{% macro helper() %}{% endmacro %}"
                    "{% macro orphan() %}{{ orphan_helper() }}{% endmacro %}"
                    "{% macro orphan_helper() %}{% endmacro %}"
                    "{% macro self_caller() %}{{ self_caller() }}{% endmacro %}"
                ),
                "page.html": '{% from "lib.html" import used %}{{ used() }}',
            }
        )
    )

    assert _unreached_library_macros(templates, "lib.html") == [
        "orphan",
        "orphan_helper",
        "self_caller",
    ]


@pytest.mark.parametrize("library", MACRO_LIBRARIES)
def test_every_library_macro_is_called_by_some_template(
    templates: dict[str, nodes.Template], library: str
) -> None:
    defined = _defined_macros(templates[library])
    called_somewhere = {
        macro
        for tree in templates.values()
        for macro in _called_library_macros(tree, library)
    }

    assert sorted(defined - called_somewhere) == [], (
        f"{library} defines macros no template calls"
    )

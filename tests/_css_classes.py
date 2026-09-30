# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to the CSS classes the dashboard applies, and to the
classes a stylesheet's selectors name.

Usage::

    from tests._css_classes import applied_classes_in_template, selector_classes

    applied = applied_classes_in_template(template_source)
    unstyled = applied - selector_classes(stylesheet_source)

A template applies classes through:

- ``class`` attributes and Alpine's six ``x-transition:<stage>`` attributes, read
  with every Jinja tag blanked, so the literal classes of every ``{% if %}``
  branch count;
- Alpine ``:class`` / ``x-bind:class`` bindings: their object keys and ternary
  branches, not the values they compare against;
- ``className`` assignments and ``classList`` add/remove/toggle/replace calls in
  inline ``<script>`` blocks, the same channel applied_classes_in_script reads
  in a standalone script;
- Jinja string constants bound to macro parameters or call keywords named
  ``classes`` or ending ``_class``.

Two gaps are known and unchecked: classes returned by Alpine methods or getters
defined in JS, and classes composed inside other Jinja expressions. Both are
false negatives, never false positives.
"""

import re
from collections.abc import Iterable
from html.parser import HTMLParser

import jinja2
from jinja2 import nodes

_JINJA = jinja2.Environment()

_CLASS_LIST_ATTRIBUTES = frozenset(
    {
        "class",
        "x-transition:enter",
        "x-transition:enter-start",
        "x-transition:enter-end",
        "x-transition:leave",
        "x-transition:leave-start",
        "x-transition:leave-end",
    }
)
_ALPINE_CLASS_BINDINGS = frozenset({":class", "x-bind:class"})

_STRING_LITERAL = re.compile(r"""'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|`((?:[^`\\]|\\.)*)`""")
_CLASS_NAME_ASSIGNMENT = re.compile(r"\.className\s*\+?=(?!=)\s*([^;]*);")
_CLASS_LIST_MUTATION = re.compile(r"\.classList\.(?:add|remove|toggle|replace)\(([^)]*)\)")

_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_INNERMOST_BLOCK = re.compile(r"\{[^{}]*\}")
_CSS_ESCAPE = r"\\([0-9a-fA-F]{1,6})\s?|\\([^0-9a-fA-F\n])"
_ESCAPED_CODE_POINT = re.compile(_CSS_ESCAPE)
_CLASS_SELECTOR = re.compile(
    rf"\.(?P<identifier>(?:[^\W\d]|-|{_CSS_ESCAPE})(?:[\w-]|{_CSS_ESCAPE})*)"
)


def applied_classes_in_template(source: str) -> set[str]:
    """Classes the Jinja template *source* applies, through every channel the module docstring lists."""
    markup = _TemplateMarkup()
    markup.feed(_markup(source))
    markup.close()
    inline_scripts = [applied_classes_in_script(body) for body in markup.script_bodies]
    return _split([*markup.class_lists, *_jinja_class_arguments(source)]).union(*inline_scripts)


def applied_classes_in_script(source: str) -> set[str]:
    """Classes the JS *source* applies through ``className`` assignments and
    ``classList`` add/remove/toggle/replace calls; reads such as comparisons do not count."""
    arguments = [
        match.group(1)
        for pattern in (_CLASS_NAME_ASSIGNMENT, _CLASS_LIST_MUTATION)
        for match in pattern.finditer(source)
    ]
    return _split(
        _literal_value(literal)
        for argument in arguments
        for literal in _STRING_LITERAL.finditer(argument)
    )


def selector_classes(stylesheet: str) -> set[str]:
    """Classes the selectors of *stylesheet* name, with CSS escapes decoded.

    Comments and declaration blocks are dropped first, so dotted text in them
    (a URL, a file name) is never read as a class; neither is a number such as
    ``.5rem`` in an at-rule prelude, because an identifier cannot start with a digit.
    """
    uncommented = _CSS_COMMENT.sub(" ", stylesheet)
    selectors_and_preludes = _INNERMOST_BLOCK.sub(" ", uncommented)
    return {
        _unescape(match["identifier"]) for match in _CLASS_SELECTOR.finditer(selectors_and_preludes)
    }


def linked_stylesheets(template_source: str) -> list[str]:
    """The .css files *template_source* links through ``url_for('static', filename=...)``, in source order."""
    calls = _JINJA.parse(template_source).find_all(nodes.Call)
    filenames = [_static_filename(call) for call in calls]
    return [name for name in filenames if name is not None and name.endswith(".css")]


class _TemplateMarkup(HTMLParser):
    """Collects the class lists and the inline script bodies of a template's literal markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.class_lists: list[str] = []
        self.script_bodies: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.class_lists.extend(
            class_list
            for name, value in attrs
            if value is not None
            for class_list in _attribute_class_lists(name, value)
        )
        if tag == "script":
            self.script_bodies.append("")
            self._in_script = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.script_bodies[-1] += data


def _markup(source: str) -> str:
    """*source* with every Jinja tag, expression and comment blanked, so the literal markup of every branch survives."""
    return "".join(value if kind == "data" else " " for _, kind, value in _JINJA.lex(source))


def _attribute_class_lists(name: str, value: str) -> list[str]:
    if name in _CLASS_LIST_ATTRIBUTES:
        return [value]
    if name in _ALPINE_CLASS_BINDINGS:
        return _alpine_class_lists(value)
    return []


def _alpine_class_lists(expression: str) -> list[str]:
    """The string literals an Alpine class binding applies: its object keys and ternary branches."""
    return [
        _literal_value(literal)
        for literal in _STRING_LITERAL.finditer(expression)
        if _is_key_or_branch(expression, literal)
    ]


def _is_key_or_branch(expression: str, literal: re.Match[str]) -> bool:
    """True when a colon follows *literal* (an object key or the first ternary
    branch), or a ``?`` or colon precedes it (a ternary branch)."""
    following = expression[literal.end() :].lstrip()
    preceding = expression[: literal.start()].rstrip()
    return following.startswith(":") or preceding.endswith(("?", ":"))


def _literal_value(literal: re.Match[str]) -> str:
    single_quoted, double_quoted, backtick_quoted = literal.groups()
    return single_quoted or double_quoted or backtick_quoted or ""


def _split(class_lists: Iterable[str]) -> set[str]:
    return {name for class_list in class_lists for name in class_list.split()}


def _jinja_class_arguments(source: str) -> list[str]:
    """String constants *source* binds to Jinja parameters named ``classes`` or ending ``_class``."""
    tree = _JINJA.parse(source)
    return [
        constant
        for parameter, value in [*_call_keywords(tree), *_macro_defaults(tree)]
        if parameter == "classes" or parameter.endswith("_class")
        for constant in _string_constants(value)
    ]


def _call_keywords(tree: nodes.Template) -> list[tuple[str, nodes.Expr]]:
    return [(keyword.key, keyword.value) for keyword in tree.find_all(nodes.Keyword)]


def _macro_defaults(tree: nodes.Template) -> list[tuple[str, nodes.Expr]]:
    """(parameter, default) for every macro parameter that has a default; the defaults belong to the last parameters."""
    return [
        (parameter.name, default)
        for macro in tree.find_all(nodes.Macro)
        for parameter, default in zip(reversed(macro.args), reversed(macro.defaults))
    ]


def _string_constants(expression: nodes.Expr) -> list[str]:
    """Every string constant in *expression*, itself included, so both branches of a conditional count."""
    candidates = [expression, *expression.find_all(nodes.Const)]
    return [value for node in candidates if (value := _string_value(node)) is not None]


def _string_value(node: nodes.Node) -> str | None:
    if isinstance(node, nodes.Const) and isinstance(node.value, str):
        return node.value
    return None


def _static_filename(call: nodes.Call) -> str | None:
    """The filename a ``url_for('static', filename=...)`` call names, or None for any other call."""
    if not _is_static_url_for(call):
        return None
    return next((_string_value(kw.value) for kw in call.kwargs if kw.key == "filename"), None)


def _is_static_url_for(call: nodes.Call) -> bool:
    return (
        isinstance(call.node, nodes.Name)
        and call.node.name == "url_for"
        and len(call.args) > 0
        and _string_value(call.args[0]) == "static"
    )


def _unescape(identifier: str) -> str:
    """*identifier* with its CSS escapes decoded as CSS Syntax §4.3.7 does."""
    return _ESCAPED_CODE_POINT.sub(_escaped_code_point, identifier)


def _escaped_code_point(escape: re.Match[str]) -> str:
    hex_digits, character = escape.groups()
    return chr(int(hex_digits, 16)) if hex_digits else character

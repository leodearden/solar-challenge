# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_css_classes.py, the reader of the CSS names the dashboard
uses and its stylesheets define: classes, custom properties and @keyframes.

Each test pins one extraction rule, so an edit that weakens a reader fails here
instead of letting a repository guard that uses it pass vacuously.
"""

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import (
    applied_classes_in_script,
    applied_classes_in_template,
    custom_property_references,
    declared_custom_properties,
    keyframes_names,
    linked_stylesheets,
    selector_classes,
)


def test_class_attribute_ignores_jinja_tags_but_counts_the_literals_of_every_branch() -> None:
    source = '<div class="p-4 {% if wide %}w-full{% else %}w-1/2{% endif %} {{ extra }}"></div>'

    assert applied_classes_in_template(source) == {"p-4", "w-full", "w-1/2"}


def test_alpine_transition_stages_are_class_lists_but_helper_modifiers_are_not() -> None:
    source = (
        '<div x-transition:enter="transition ease-out duration-200"'
        ' x-transition:leave-end="opacity-0 scale-95"'
        " x-transition.duration.300ms></div>"
    )

    assert applied_classes_in_template(source) == {
        "transition",
        "ease-out",
        "duration-200",
        "opacity-0",
        "scale-95",
    }


def test_alpine_binding_counts_object_keys_and_ternary_branches_not_compared_values() -> None:
    """Neither 'overview' nor 'dark' is a class: each is only compared against."""
    source = (
        "<a :class=\"{ 'bg-amber-50 text-amber-700': tab === 'overview', 'opacity-0': !open }\"></a>"
        "<b x-bind:class=\"mode === 'dark' ? 'text-white' : 'text-slate-900'\"></b>"
    )

    assert applied_classes_in_template(source) == {
        "bg-amber-50",
        "text-amber-700",
        "opacity-0",
        "text-white",
        "text-slate-900",
    }


def test_inline_script_in_a_template_counts_its_class_assignments() -> None:
    source = (
        "<script>el.className = 'flex gap-3' + (mine ? ' flex-row-reverse' : '');"
        " el.classList.add('hidden'); el.dataset.role = 'user';</script>"
    )

    assert applied_classes_in_template(source) == {"flex", "gap-3", "flex-row-reverse", "hidden"}


def test_jinja_class_parameters_count_macro_defaults_and_call_keywords_in_both_branches() -> None:
    """Only parameters named ``classes`` or ending ``_class`` carry classes; ``label`` and ``title`` do not."""
    source = (
        '{% macro icon(label="Icon", classes="h-5 w-5") %}<svg class="{{ classes }}"></svg>{% endmacro %}'
        '{{ icon(classes="h-4 w-4" if small else "h-6 w-6") }}'
        '{{ dialog(title="Delete run", confirm_class="bg-red-600 hover:bg-red-700") }}'
    )

    assert applied_classes_in_template(source) == {
        "h-5",
        "w-5",
        "h-4",
        "w-4",
        "h-6",
        "w-6",
        "bg-red-600",
        "hover:bg-red-700",
    }


def test_script_counts_class_name_assignments_and_class_list_mutations_but_not_reads() -> None:
    source = (
        "bubble.className = 'rounded-lg px-4 ' +\n"
        "  (isUser ? 'bg-amber-500 text-white' : 'bg-slate-50');\n"
        "bubble.className += ' shadow';\n"
        "el.classList.toggle('ring-2', active);\n"
        "el.classList.replace('opacity-0', 'opacity-100');\n"
        "if (el.className === 'not-a-class') {}\n"
        "document.documentElement.classList.contains('dark');\n"
    )

    assert applied_classes_in_script(source) == {
        "rounded-lg",
        "px-4",
        "bg-amber-500",
        "text-white",
        "bg-slate-50",
        "shadow",
        "ring-2",
        "opacity-0",
        "opacity-100",
    }


def test_selector_classes_decode_escapes_and_skip_comments_preludes_and_declarations() -> None:
    """Nothing from '.com', '.5rem' or '.svg' is a class: they sit in a comment, a prelude and a value."""
    stylesheet = (
        r"/*! tailwindcss v3.4.19 | MIT License | https://tailwindcss.com*/"
        r".w-1\/2{width:50%}"
        r".space-y-8>:not([hidden])~:not([hidden]){margin-top:2rem}"
        r".dark\:border-amber-700:is(.dark *){border-color:#b45309}"
        r".focus\:border-transparent:focus{border-color:transparent}"
        r"@media (min-width:40.5rem){.sm\:px-6{padding-left:1.5rem}}"
        r".\32xl\:p-4{padding:1rem}"
        r".bg-dot{background:url(icons/dot.svg) 0 .5rem}"
    )

    assert selector_classes(stylesheet) == {
        "w-1/2",
        "space-y-8",
        "dark:border-amber-700",
        "dark",
        "focus:border-transparent",
        "sm:px-6",
        "2xl:p-4",
        "bg-dot",
    }


def test_selector_classes_skip_strings_and_url_tokens() -> None:
    """Neither '.css' nor '.pdf' is a class: they sit in a url() and an attribute string.
    The escaped quotes of content-[''] open no string."""
    stylesheet = (
        r"@import url(vendor/reset.css);"
        r'a[href$=".pdf"]{color:red}'
        r".content-\[\'\'\]{--tw-content:''}"
    )

    assert selector_classes(stylesheet) == {"content-['']"}


def test_declared_custom_properties_skip_comments_strings_var_reads_and_bem_modifiers() -> None:
    """None of '--commented-out', '--in-a-string', '--only-read' or '--lg' is declared: they sit
    in a comment, a string, a var() read and a BEM class name."""
    stylesheet = (
        "/* --commented-out: red; */"
        ":root{--color-primary:#f59e0b;--tw-content:'--in-a-string: 1'}"
        "html.dark { --color-primary : #fbbf24 }"
        ".spinner--lg:hover{color:var(--only-read)}"
    )

    assert declared_custom_properties(stylesheet) == {"--color-primary", "--tw-content"}


def test_custom_property_references_are_the_var_reads_of_any_source_including_nested_fallbacks() -> None:
    """'--color-unread' is only declared, never read."""
    source = (
        "input::-moz-range-thumb{background:var(--color-primary)}"
        "*{box-shadow:var(--tw-ring-offset-shadow,var( --tw-ring-shadow ))}"
        '<div style="color: var(--color-generation)"></div>'
        ":root{--color-unread:#fff}"
    )

    assert custom_property_references(source) == {
        "--color-primary",
        "--tw-ring-offset-shadow",
        "--tw-ring-shadow",
        "--color-generation",
    }


def test_keyframes_names_count_keyframes_rules_including_vendor_prefixed_but_not_animations_or_comments() -> None:
    """Neither 'banner' nor 'bounce' is defined: one sits in a comment, the other is only
    named by an animation."""
    stylesheet = (
        "/*! @keyframes banner */"
        "@keyframes spin{to{transform:rotate(1turn)}}"
        "@-webkit-keyframes pulse { 50% { opacity: .5 } }"
        ".animate-bounce{animation:bounce 1s infinite}"
    )

    assert keyframes_names(stylesheet) == {"spin", "pulse"}


def test_linked_stylesheets_are_the_static_css_files_in_source_order() -> None:
    source = (
        "<link rel=\"icon\" href=\"{{ url_for('static', filename='favicon.svg') }}\" type=\"image/svg+xml\">"
        "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='dist/style.css') }}\">"
        "<a href=\"{{ url_for('main.index') }}\">Solar Challenge</a>"
        "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='style.css') }}\">"
    )

    assert linked_stylesheets(source) == ["dist/style.css", "style.css"]

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_css_classes.py, the reader of the CSS names the dashboard
uses and its stylesheets define: classes, custom properties, @keyframes, and the
properties class rules declare and inline styles set.

Each test pins one extraction rule, so an edit that weakens a reader fails here
instead of letting a repository guard that uses it pass vacuously.
"""

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import (
    InlineStyledElement,
    applied_classes_in_script,
    applied_classes_in_template,
    custom_property_references,
    declared_custom_properties,
    declared_properties_by_class,
    inline_styled_elements,
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
        "html.dark { --spaced-before-colon : #fbbf24 }"
        ".spinner--lg:hover{color:var(--only-read)}"
    )

    assert declared_custom_properties(stylesheet) == {
        "--color-primary",
        "--tw-content",
        "--spaced-before-colon",
    }


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


def test_declared_properties_by_class_read_lone_class_rules_at_any_media_depth_but_not_important_declarations() -> None:
    """A pseudo-class, descendant, pseudo-element or attribute selector is not a lone class, so
    hover:bg-amber-600, dark, dark:text-white, scrollbar-hide and x-cloak declare nothing here.
    !mt-0's margin-top is !important, which no inline style overrides."""
    stylesheet = (
        r"/*! tailwindcss v3.4.19 | MIT License | https://tailwindcss.com*/"
        r".chart-container{width:100%}"
        r"@media (max-width:48rem){.chart-container{min-height:280px}}"
        r".w-1\/2,.basis-1\/2{flex-basis:50%}"
        r".hover\:bg-amber-600:hover{background-color:#d97706}"
        r".dark .dark\:text-white{color:#fff}"
        r".scrollbar-hide::-webkit-scrollbar{display:none}"
        r".\!mt-0{margin-top:0!important;padding-top:0}"
        r"[x-cloak]{display:none !important}"
    )

    assert declared_properties_by_class(stylesheet) == {
        "chart-container": {"width", "min-height"},
        "w-1/2": {"flex-basis"},
        "basis-1/2": {"flex-basis"},
        "!mt-0": {"padding-top"},
    }


def test_declared_properties_by_class_read_rules_inside_media_supports_and_layer_blocks_only() -> None:
    """md:grid sits two at-rules deep and btn sits in a @layer block, so both count. Under native
    CSS nesting, card-title reads ``.card .card-title``, a descendant selector, and @scope and
    @container limit scoped-only and contained-only to some elements of their class. So none of
    those three declares anything, and neither does card, because it nests a rule."""
    stylesheet = (
        r".card{color:red;.card-title{min-height:0}}"
        r"@scope (.panel){.scoped-only{padding:0}}"
        r"@container (min-width:20rem){.contained-only{display:flex}}"
        r"@supports (display:grid){@media (min-width:40rem){.md\:grid{display:grid}}}"
        r"@layer components{.btn{cursor:pointer}}"
    )

    assert declared_properties_by_class(stylesheet) == {
        "md:grid": {"display"},
        "btn": {"cursor"},
    }


def test_declared_properties_by_class_tolerate_spacing_an_import_statement_a_stray_brace_an_upper_case_at_rule_and_a_spaced_upper_case_important() -> None:
    """Each tolerance has a class of its own: an @import statement just before a rule (sr-only),
    an upper-case at-keyword with no whitespace before it (grid-flow-dense), whitespace before a
    brace (scrollbar-hide) and around a comma (inset-x-0, inset-y-0), whitespace before a
    lower-case at-keyword (print:hidden), and a stray closing brace just before a rule
    (after-stray-brace). The spaced, upper-case ``! IMPORTANT`` still marks left as important."""
    stylesheet = (
        r'@import url("vendor/reset.css");'
        r".sr-only{position:absolute}"
        r"@SUPPORTS (display:grid){.grid-flow-dense{grid-auto-flow:dense}}"
        ".scrollbar-hide {\n    scrollbar-width: none;\n}\n"
        ".inset-x-0 , .inset-y-0 {\n    left: 0 ! IMPORTANT;\n    top: 0;\n}\n"
        "@media print {\n    .print\\:hidden { display: none; }\n}\n"
        r"}.after-stray-brace{bottom:0}"
    )

    assert declared_properties_by_class(stylesheet) == {
        "sr-only": {"position"},
        "grid-flow-dense": {"grid-auto-flow"},
        "scrollbar-hide": {"scrollbar-width"},
        "inset-x-0": {"top"},
        "inset-y-0": {"top"},
        "print:hidden": {"display"},
        "after-stray-brace": {"bottom"},
    }


def test_inline_styled_elements_pair_a_static_style_with_the_classes_its_element_applies() -> None:
    """The w-full span has no style attribute, and the h-full paragraph's :style binding is not
    read, so neither is listed. The string 'a;b: c' sets no property b."""
    source = (
        '<div id="{{ id }}" class="chart-container {{ extra }}"'
        ' style="width: 100%; min-height: {{ height }};"></div>'
        "<div class=\"grid\" :class=\"open ? 'gap-4' : 'gap-2'\""
        " style=\"grid-template-columns: repeat({{ n }}, 1fr); content: 'a;b: c'\"></div>"
        '<span class="w-full"></span>'
        "<p class=\"h-full\" :style=\"'width: ' + pct + '%'\"></p>"
    )

    assert inline_styled_elements(source) == [
        InlineStyledElement(
            classes=frozenset({"chart-container"}),
            inline_properties=frozenset({"width", "min-height"}),
        ),
        InlineStyledElement(
            classes=frozenset({"grid", "gap-4", "gap-2"}),
            inline_properties=frozenset({"grid-template-columns", "content"}),
        ),
    ]


def test_declared_and_inline_property_names_are_lower_cased_except_custom_properties() -> None:
    """CSS matches a property name case-insensitively, a vendor-prefixed one included, so both
    readers lower-case it; a custom property's name is case-sensitive, so --Bar-Color keeps its case."""
    stylesheet = ".line-clamp-3{-WebKit-Line-Clamp:3;--Bar-Color:#f59e0b}"
    source = '<p class="line-clamp-3" style="-WEBKIT-LINE-CLAMP: 2; --Bar-Color: red"></p>'

    assert declared_properties_by_class(stylesheet) == {
        "line-clamp-3": {"-webkit-line-clamp", "--Bar-Color"}
    }
    assert inline_styled_elements(source) == [
        InlineStyledElement(
            classes=frozenset({"line-clamp-3"}),
            inline_properties=frozenset({"-webkit-line-clamp", "--Bar-Color"}),
        )
    ]

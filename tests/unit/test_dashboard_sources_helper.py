# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_dashboard_sources.py, which reads the dashboard's source files.

The web guards read the classes the dashboard applies through
dashboard_applied_classes_by_source, so a source it skips or misreads goes unchecked by
every guard. tests/_dashboard_sources.py's templates and scripts are the files the content
globs of tailwind.config.js select, so a glob it misreads or cannot expand leaves files
Tailwind scans unchecked by every guard.
"""

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import applied_classes_in_script, applied_classes_in_template
from tests._dashboard_sources import (
    TAILWIND_CONFIG_KEY,
    dashboard_applied_classes_by_source,
    dashboard_script_sources,
    dashboard_template_sources,
    files_by_content_glob,
    tailwind_content_globs,
)


def test_applied_classes_by_source_cover_every_template_and_script_under_its_source_key() -> None:
    sources = [*dashboard_template_sources(), *dashboard_script_sources()]

    assert sorted(dashboard_applied_classes_by_source()) == sorted(sources), (
        "dashboard_applied_classes_by_source must key the classes of every dashboard template "
        "and script exactly as dashboard_template_sources and dashboard_script_sources key its "
        "source, or every web guard that reads it skips that source"
    )


def test_applied_classes_by_source_read_each_source_with_the_reader_for_its_kind() -> None:
    read_as_templates = {
        path: applied_classes_in_template(source)
        for path, source in dashboard_template_sources().items()
    }
    read_as_scripts = {
        path: applied_classes_in_script(source)
        for path, source in dashboard_script_sources().items()
    }

    assert dashboard_applied_classes_by_source() == read_as_templates | read_as_scripts, (
        "dashboard_applied_classes_by_source must read each dashboard template with "
        "applied_classes_in_template and each script with applied_classes_in_script, or every "
        "web guard that reads it sees the wrong classes for that source"
    )


@pytest.mark.parametrize(
    ("config_source", "globs"),
    [
        pytest.param(
            "module.exports = {\n"
            "  darkMode: 'class',\n"
            "  content: [\n"
            "    './pages/**/*.html',\n"
            "    './assets/js/**/*.js',\n"
            "  ],\n"
            "  theme: { extend: { colors: { brand: { 50: '#ffffff' } } } },\n"
            "};\n",
            ["./pages/**/*.html", "./assets/js/**/*.js"],
            id="multi-line single-quoted array with a trailing comma",
        ),
        pytest.param(
            'content: ["./views/**/*.html", "./bundles/*.js"]',
            ["./views/**/*.html", "./bundles/*.js"],
            id="one-line double-quoted array",
        ),
        pytest.param(
            "content: ['./partials/*.[jh]tml']",
            ["./partials/*.[jh]tml"],
            id="character class",
        ),
    ],
)
def test_tailwind_content_globs_read_the_quoted_globs_of_the_content_array_in_source_order(
    config_source: str, globs: list[str]
) -> None:
    assert tailwind_content_globs(config_source) == globs


@pytest.mark.parametrize(
    ("config_source", "count"),
    [
        pytest.param("content: { files: ['./pages/**/*.html'] }", 0, id="object form"),
        pytest.param(
            "content: [\n    './pages/**/*.html',\n    // './legacy/**/*.html',\n  ],",
            0,
            id="commented-out entry",
        ),
        pytest.param(
            "content: ['./pages/**/*.html'],\n/* content: ['./legacy/**/*.html'], */",
            2,
            id="two content arrays",
        ),
    ],
)
def test_tailwind_content_globs_fail_naming_the_count_unless_one_content_array_lists_only_quoted_globs(
    config_source: str, count: int
) -> None:
    with pytest.raises(AssertionError) as failure:
        tailwind_content_globs(config_source)

    assert f"read {count} content arrays" in str(failure.value)


def test_every_tailwind_content_glob_selects_a_file() -> None:
    selected = files_by_content_glob()
    assert selected, (
        f"read no content glob from {TAILWIND_CONFIG_KEY}, so this check would pass vacuously"
    )
    empty = [glob for glob, files in selected.items() if not files]

    assert empty == [], (
        f"these content globs of {TAILWIND_CONFIG_KEY} select no file: {' '.join(empty)}\n"
        "If the files a glob selected moved, Tailwind scans nothing through it either: point it "
        "at them, or delete it. If it uses syntax pathlib's glob cannot expand, such as {a,b} "
        "braces or a ! negation, the web guards miss files Tailwind scans: rewrite it with *, ** "
        "and ?, or extend files_by_content_glob in tests/_dashboard_sources.py."
    )


def test_the_dashboard_templates_and_scripts_are_the_files_tailwind_scans() -> None:
    scanned = sorted({key for files in files_by_content_glob().values() for key in files})
    read = sorted([*dashboard_template_sources(), *dashboard_script_sources()])

    assert read == scanned, (
        "the web guards must read exactly the files Tailwind scans for the classes the dashboard "
        "applies, each as a template (.html) or a script (.js)\n"
        f"scanned but not read: {' '.join(sorted(set(scanned) - set(read)))}\n"
        "tests/_dashboard_sources.py has no reader for the kind of those files: give it one, or "
        "narrow the glob that selects them.\n"
        f"read but not scanned: {' '.join(sorted(set(read) - set(scanned)))}"
    )

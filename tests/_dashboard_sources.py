# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read access to the source files of the solar_challenge.web dashboard: its Jinja
templates, its standalone scripts, the stylesheets base.html links and
tailwind.config.js, which defines its theme.

Each template, script and stylesheet is keyed by its POSIX path relative to the
package directory, such as ``templates/base.html``, ``static/js/chart-renderer.js``
or ``static/style.css``. tailwind.config.js is keyed the same way, as
``tailwind.config.js``. The template and script globs mirror the ``content`` globs
in tailwind.config.js, which select the files Tailwind scans for the classes the
dashboard applies; dashboard_applied_classes_by_source reads those classes from the
same files, under the same keys.

Usage::

    from tests._dashboard_sources import (
        BASE_TEMPLATE_KEY,
        dashboard_template_sources,
        served_stylesheet_sources,
    )

    base_layout = dashboard_template_sources()[BASE_TEMPLATE_KEY]
    stylesheets = list(served_stylesheet_sources())
"""

import re
from collections.abc import Iterable
from pathlib import Path

import solar_challenge.web
from tests._css_classes import (
    applied_classes_in_script,
    applied_classes_in_template,
    linked_stylesheets,
)

_WEB_DIR = Path(solar_challenge.web.__file__).parent
_STATIC_DIR = _WEB_DIR / "static"
BASE_TEMPLATE_KEY = "templates/base.html"
_BASE_TEMPLATE = _WEB_DIR / BASE_TEMPLATE_KEY
HAND_WRITTEN_STYLESHEET_KEY = "static/style.css"
TAILWIND_CONFIG_KEY = "tailwind.config.js"
_QUOTED_STRING = r"""(?:'[^']*'|"[^"]*")"""
_CONTENT_ARRAY = re.compile(
    rf"\bcontent\s*:\s*\[\s*((?:{_QUOTED_STRING}\s*(?:,\s*{_QUOTED_STRING}\s*)*(?:,\s*)?)?)\]"
)


def dashboard_template_sources() -> dict[str, str]:
    """Source of every Jinja template under templates/, in path order."""
    return _sources(sorted((_WEB_DIR / "templates").rglob("*.html")))


def dashboard_script_sources() -> dict[str, str]:
    """Source of every standalone script under static/js/, in path order."""
    return _sources(sorted((_STATIC_DIR / "js").rglob("*.js")))


def dashboard_applied_classes_by_source() -> dict[str, set[str]]:
    """Classes each template and script applies, as tests/_css_classes.py reads them, under its key."""
    templates = {
        path: applied_classes_in_template(source)
        for path, source in dashboard_template_sources().items()
    }
    scripts = {
        path: applied_classes_in_script(source)
        for path, source in dashboard_script_sources().items()
    }
    return templates | scripts


def served_stylesheet_sources() -> dict[str, str]:
    """Source of every stylesheet base.html links through ``url_for('static', ...)``, in link order."""
    linked = linked_stylesheets(_BASE_TEMPLATE.read_text(encoding="utf-8"))
    return _sources(_STATIC_DIR / name for name in linked)


def hand_written_stylesheet_source() -> str:
    """Source of static/style.css, the stylesheet base.html serves as-is, never compiled.

    Fails if base.html no longer links it."""
    served = served_stylesheet_sources()
    assert HAND_WRITTEN_STYLESHEET_KEY in served, (
        f"base.html no longer links {HAND_WRITTEN_STYLESHEET_KEY}, so none of its rules apply: "
        "delete the file or link it again"
    )
    return served[HAND_WRITTEN_STYLESHEET_KEY]


def tailwind_config_source() -> str:
    """Source of tailwind.config.js, the home of the dashboard's theme."""
    return (_WEB_DIR / TAILWIND_CONFIG_KEY).read_text(encoding="utf-8")


def tailwind_content_globs(config_source: str) -> list[str]:
    """Globs of the one ``content`` array in the Tailwind config *config_source*, in source order.

    Reads only ``content: ['glob', "glob"]``, a bare key whose array lists nothing but quoted
    strings, and fails on any other form rather than guess."""
    arrays = _CONTENT_ARRAY.findall(config_source)
    assert len(arrays) == 1, (
        f"read {len(arrays)} content arrays of quoted globs from {TAILWIND_CONFIG_KEY}, where "
        "tests/_dashboard_sources.py needs exactly one: it reads the dashboard's templates and "
        "scripts through these globs, so it must not guess which files Tailwind scans. Write "
        "content as one array of quoted globs, with no comment, object, spread or files: form "
        "inside, or extend tailwind_content_globs to read the new form"
    )
    return [quoted[1:-1] for quoted in re.findall(_QUOTED_STRING, arrays[0])]


def _sources(paths: Iterable[Path]) -> dict[str, str]:
    return {
        path.relative_to(_WEB_DIR).as_posix(): path.read_text(encoding="utf-8") for path in paths
    }

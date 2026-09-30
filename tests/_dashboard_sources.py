# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read access to the source files of the solar_challenge.web dashboard: its Jinja
templates, its standalone scripts and the stylesheets base.html links.

Each source is keyed by its POSIX path relative to the package directory, such as
``templates/base.html``, ``static/js/chart-renderer.js`` or ``static/style.css``.
The template and script globs mirror the ``content`` globs in tailwind.config.js.

Usage::

    from tests._dashboard_sources import dashboard_template_sources, served_stylesheet_sources

    base_layout = dashboard_template_sources()["templates/base.html"]
    stylesheets = list(served_stylesheet_sources())
"""

from collections.abc import Iterable
from pathlib import Path

import solar_challenge.web
from tests._css_classes import linked_stylesheets

_WEB_DIR = Path(solar_challenge.web.__file__).parent
_STATIC_DIR = _WEB_DIR / "static"
_BASE_TEMPLATE = _WEB_DIR / "templates" / "base.html"


def dashboard_template_sources() -> dict[str, str]:
    """Source of every Jinja template under templates/, in path order."""
    return _sources(sorted((_WEB_DIR / "templates").rglob("*.html")))


def dashboard_script_sources() -> dict[str, str]:
    """Source of every standalone script under static/js/, in path order."""
    return _sources(sorted((_STATIC_DIR / "js").rglob("*.js")))


def served_stylesheet_sources() -> dict[str, str]:
    """Source of every stylesheet base.html links through ``url_for('static', ...)``, in link order."""
    linked = linked_stylesheets(_BASE_TEMPLATE.read_text(encoding="utf-8"))
    return _sources(_STATIC_DIR / name for name in linked)


def _sources(paths: Iterable[Path]) -> dict[str, str]:
    return {
        path.relative_to(_WEB_DIR).as_posix(): path.read_text(encoding="utf-8") for path in paths
    }

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read access to the source files of the solar_challenge.web dashboard: its Jinja
templates, its standalone scripts, the stylesheets base.html links, its Python modules,
the JavaScript files at the package root, and the theme token file
static/src/theme-tokens.json, the one home of the dashboard's colours: tailwind.config.js
reads its tailwind section and charts.py its chart section. tailwind_role_palettes reads
the tailwind section's roles under the palette names their classes write, such as
``status-running`` for the ``running`` role of the ``status`` group.

Each template, script, stylesheet, Python module, JavaScript file at the package root
and the token file is keyed by its POSIX path relative to the package directory, such as
``templates/base.html``, ``static/js/chart-renderer.js``, ``static/style.css``,
``charts.py``, ``tailwind.config.js`` or ``static/src/theme-tokens.json``. The templates
and scripts are the ``.html`` and ``.js`` files the ``content`` globs of
tailwind.config.js select, the files Tailwind scans for the classes the dashboard applies.
dashboard_applied_classes_by_source reads those classes from the same files, under the
same keys. pathlib expands each glob relative to the package directory, and it has no
``{a,b}`` braces or ``!`` negation.

Usage::

    from tests._dashboard_sources import (
        BASE_TEMPLATE_KEY,
        dashboard_template_sources,
        served_stylesheet_sources,
    )

    base_layout = dashboard_template_sources()[BASE_TEMPLATE_KEY]
    stylesheets = list(served_stylesheet_sources())
"""

import json
import re
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

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
FAVICON_BUILDER_KEY = "build-favicon.js"
THEME_TOKENS_KEY = "static/src/theme-tokens.json"
_NPM_PACKAGES_DIR = "node_modules"
_QUOTED_STRING = r"""(?:'[^']*'|"[^"]*")"""
_CONTENT_ARRAY = re.compile(
    rf"\bcontent\s*:\s*\[\s*((?:{_QUOTED_STRING}\s*(?:,\s*{_QUOTED_STRING}\s*)*(?:,\s*)?)?)\]"
)


def dashboard_template_sources() -> dict[str, str]:
    """Source of every Jinja template, in path order.

    A template is an .html file a content glob of tailwind.config.js selects."""
    return _scanned_sources_with_suffix(".html")


def dashboard_script_sources() -> dict[str, str]:
    """Source of every standalone script, in path order.

    A script is a .js file a content glob of tailwind.config.js selects."""
    return _scanned_sources_with_suffix(".js")


def dashboard_python_sources() -> dict[str, str]:
    """Source of every Python module of the package, such as ``charts.py``, in path order.

    A module is a .py file anywhere under the package directory but in npm's node_modules."""
    return _sources(
        path
        for path in sorted(_WEB_DIR.rglob("*.py"))
        if _NPM_PACKAGES_DIR not in path.relative_to(_WEB_DIR).parts
    )


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
    """Source of tailwind.config.js, which builds the dashboard's Tailwind theme from the token file's tailwind section."""
    return (_WEB_DIR / TAILWIND_CONFIG_KEY).read_text(encoding="utf-8")


def package_root_javascript_sources() -> dict[str, str]:
    """Source of every JavaScript file directly in the package directory, such as tailwind.config.js
    and build-favicon.js, in path order.

    These are the files Node runs when npm builds static/dist. Flask serves none of them, and
    Tailwind scans none."""
    return _sources(sorted(path for path in _WEB_DIR.glob("*.js") if path.is_file()))


def theme_tokens_source() -> str:
    """Source of static/src/theme-tokens.json, the one home of the dashboard's colours.

    tailwind.config.js reads its tailwind section, and charts.py its chart section."""
    return (_WEB_DIR / THEME_TOKENS_KEY).read_text(encoding="utf-8")


def theme_tokens() -> dict[str, Any]:
    """The token file theme_tokens_source reads, parsed afresh on each call, so a test may edit its copy."""
    tokens: dict[str, Any] = json.loads(theme_tokens_source())
    return tokens


def tailwind_role_palettes(section: Mapping[str, Any]) -> dict[str, str]:
    """The built-in palette each role of the token file's tailwind *section* names, keyed by the
    palette name the role's classes write, in section order.

    A JSON object value is a group of roles, each keyed by the group's key and its own joined by
    a hyphen, at any depth, as tailwind.config.js names it: the ``running`` role of the
    ``status`` group is ``status-running``, applied as ``bg-status-running-100``. Raises
    ValueError naming dotted paths, such as ``tailwind.status.running``, as tailwind.config.js's
    refusals do: for a value that is neither a palette's name nor a group, and for two roles
    keyed alike, such as a ``status-running`` role beside the ``status`` group's ``running``.
    Only the build knows which names are built-in Tailwind palettes."""
    palettes: dict[str, str] = {}
    paths: dict[str, str] = {}
    for role, palette in _role_palettes(section, ()):
        name, path = "-".join(role), ".".join(role)
        if name in paths:
            raise ValueError(
                f"{THEME_TOKENS_KEY}: tailwind.{paths[name]} and tailwind.{path} both define the "
                f"Tailwind colour {name}, so one of their palettes would silently replace the other"
            )
        palettes[name] = palette
        paths[name] = path
    return palettes


def _role_palettes(
    section: Mapping[str, Any], group: tuple[str, ...]
) -> Iterator[tuple[tuple[str, ...], str]]:
    for key, value in section.items():
        role = (*group, key)
        if isinstance(value, Mapping):
            yield from _role_palettes(value, role)
        elif isinstance(value, str):
            yield role, value
        else:
            raise ValueError(
                f"{THEME_TOKENS_KEY}: tailwind.{'.'.join(role)} names {json.dumps(value)}, which is "
                "neither a built-in Tailwind palette's name nor a group of roles"
            )


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


def files_by_content_glob() -> dict[str, list[str]]:
    """Keys of the files each ``content`` glob of tailwind.config.js selects, by glob.

    Globs come in source order, each expanded by pathlib relative to the package directory:
    files only, in path order. pathlib has no ``{a,b}`` braces or ``!`` negation, so a glob
    using them selects nothing."""
    return {
        glob: [_source_key(path) for path in sorted(_WEB_DIR.glob(glob)) if path.is_file()]
        for glob in tailwind_content_globs(tailwind_config_source())
    }


def _scanned_sources_with_suffix(suffix: str) -> dict[str, str]:
    scanned = {_WEB_DIR / key for keys in files_by_content_glob().values() for key in keys}
    return _sources(sorted(path for path in scanned if path.suffix == suffix))


def _sources(paths: Iterable[Path]) -> dict[str, str]:
    return {_source_key(path): path.read_text(encoding="utf-8") for path in paths}


def _source_key(path: Path) -> str:
    return path.relative_to(_WEB_DIR).as_posix()

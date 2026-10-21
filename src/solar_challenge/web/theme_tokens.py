# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reader of the dashboard's theme token file, static/src/theme-tokens.json, the one home of its colours.

The file's sections and the rules a reader enforces are docs/prds/chart-panels-and-theme-tokens.md
§Contract: tailwind.config.js reads the tailwind section, and chart_colour_palette the chart section,
whose hues are colours written #rrggbb and whose roles each name a hue.
"""

import json
import re
from pathlib import Path
from typing import TypeGuard

_RRGGBB = re.compile(r"#[0-9a-fA-F]{6}")


def is_rrggbb(colour: object) -> TypeGuard[str]:
    """Whether *colour* is a str written #rrggbb: a hash and six hex digits, in either case."""
    return isinstance(colour, str) and _RRGGBB.fullmatch(colour) is not None


def chart_colour_palette(tokens_file: Path) -> dict[str, str]:
    """Each chart role of *tokens_file*, in the file's order, mapped to the colour of the hue it names.

    Raises:
        ValueError: If the file is not a JSON object, or its chart section, or the chart
            section's hues or roles, is missing or not a JSON object, naming the file and the
            section; if a chart hue is not written #rrggbb, naming the file, the hue and its
            value; or if a chart role names no chart hue, naming the file, the role, what it
            names and the hues.
    """
    tokens = json.loads(tokens_file.read_text(encoding="utf-8"))
    written_hues = _section(tokens_file, tokens, ("chart", "hues"))
    written_roles = _section(tokens_file, tokens, ("chart", "roles"))
    hues: dict[str, str] = {}
    for hue, colour in written_hues.items():
        if not is_rrggbb(colour):
            raise ValueError(f"{tokens_file}: the chart hue {hue!r} is {colour!r}, not a colour written #rrggbb")
        hues[hue] = colour
    palette: dict[str, str] = {}
    for role, named in written_roles.items():
        if not (isinstance(named, str) and named in hues):
            raise ValueError(
                f"{tokens_file}: the chart role {role!r} names {named!r}, which is not one of the chart hues {list(hues)}"
            )
        palette[role] = hues[named]
    return palette


def _section(tokens_file: Path, tokens: object, keys: tuple[str, ...]) -> dict[str, object]:
    """The JSON object *keys* name in *tokens*, the parsed *tokens_file*: each key a member of the object before it.

    Raises:
        ValueError: If *tokens*, or a member a key names, is not a JSON object, or a key names
            no member, naming the file and the section, its keys joined by dots.
    """
    section = _json_object(tokens_file, tokens, "the top level")
    for depth, key in enumerate(keys, start=1):
        where = ".".join(keys[:depth])
        if key not in section:
            raise ValueError(f"{tokens_file}: the {where!r} section is missing")
        section = _json_object(tokens_file, section[key], f"the {where!r} section")
    return section


def _json_object(tokens_file: Path, value: object, what: str) -> dict[str, object]:
    """*value*, which *what* names in *tokens_file*, refused unless it is a JSON object."""
    if not isinstance(value, dict):
        raise ValueError(f"{tokens_file}: {what} must be a JSON object, got {type(value).__name__}")
    return value

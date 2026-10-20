# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reader of the dashboard's theme token file, static/src/theme-tokens.json, the one home of its colours.

The file's sections and the rules a reader enforces are docs/prds/chart-panels-and-theme-tokens.md
§Contract: tailwind.config.js reads the tailwind section, and chart_colour_palette the chart section,
whose hues are colours written #rrggbb and whose roles each name a hue.
"""

import json
import re
from pathlib import Path

_RRGGBB = re.compile(r"#[0-9a-fA-F]{6}")


def is_rrggbb(colour: object) -> bool:
    """Whether *colour* is a str written #rrggbb: a hash and six hex digits, in either case."""
    return isinstance(colour, str) and _RRGGBB.fullmatch(colour) is not None


def chart_colour_palette(tokens_file: Path) -> dict[str, str]:
    """Each chart role of *tokens_file*, in the file's order, mapped to the colour of the hue it names.

    Raises:
        ValueError: If a chart hue is not written #rrggbb, naming the file, the hue and its value;
            or if a chart role names no chart hue, naming the file, the role, what it names and
            the hues.
    """
    chart = json.loads(tokens_file.read_text(encoding="utf-8"))["chart"]
    hues: dict[str, str] = {}
    for hue, colour in chart["hues"].items():
        if not is_rrggbb(colour):
            raise ValueError(f"{tokens_file}: the chart hue {hue!r} is {colour!r}, not a colour written #rrggbb")
        hues[hue] = colour
    palette: dict[str, str] = {}
    for role, hue in chart["roles"].items():
        if not (isinstance(hue, str) and hue in hues):
            raise ValueError(
                f"{tokens_file}: the chart role {role!r} names {hue!r}, which is not one of the chart hues {list(hues)}"
            )
        palette[role] = hues[hue]
    return palette
